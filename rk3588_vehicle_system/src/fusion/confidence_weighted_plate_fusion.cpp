#include "fusion/confidence_weighted_plate_fusion.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <iterator>
#include <limits>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace vehicle_system {
namespace {

constexpr double kWeightEpsilon = 1.0e-12;

template <typename Sample>
void keep_history_limit(std::deque<Sample>& samples, std::size_t limit) {
    while (samples.size() > limit) {
        samples.pop_front();
    }
}

}  // namespace

struct ConfidenceWeightedPlateFusion::Impl {
    struct TextSample {
        std::uint64_t frame_id = 0;
        float quality = 0.0F;
        PlateOCRResult ocr;

        double weight() const {
            return static_cast<double>(quality) * static_cast<double>(ocr.confidence);
        }
    };

    struct ColorSample {
        std::uint64_t frame_id = 0;
        float quality = 0.0F;
        ColorResult color;

        double weight() const {
            return static_cast<double>(quality) * static_cast<double>(color.confidence);
        }
    };

    struct TrackHistory {
        std::deque<TextSample> text_samples;
        std::deque<ColorSample> color_samples;
        std::uint64_t last_seen_frame = 0;
        bool has_last_seen_frame = false;
    };

    struct Aggregate {
        double weight = 0.0;
        double quality_sum = 0.0;
        double quality_confidence_sum = 0.0;
        std::size_t count = 0;
        std::uint64_t latest_frame = 0;
    };

    explicit Impl(const PlateFusionConfig& fusion_config) : config(fusion_config) {
        if (config.max_history_per_track <= 0 || config.top_k <= 0 ||
            config.top_k > config.max_history_per_track) {
            throw std::invalid_argument(
                "PlateFusion history and top_k must satisfy 1 <= top_k <= history");
        }
        if (config.min_samples <= 0 || config.min_samples > config.top_k ||
            config.min_winner_samples <= 0 ||
            config.min_winner_samples > config.min_samples) {
            throw std::invalid_argument("PlateFusion sample thresholds are invalid");
        }
        const auto valid_unit = [](float value) {
            return std::isfinite(value) && value >= 0.0F && value <= 1.0F;
        };
        if (!valid_unit(config.min_ocr_confidence) ||
            !valid_unit(config.min_quality_score) ||
            !valid_unit(config.min_vote_ratio) ||
            !valid_unit(config.min_color_confidence)) {
            throw std::invalid_argument("PlateFusion confidence thresholds must be within [0, 1]");
        }
        if (config.stale_after_frames < 0) {
            throw std::invalid_argument("PlateFusion stale_after_frames must be non-negative");
        }
    }

    template <typename Sample>
    std::vector<const Sample*> top_quality_samples(const std::deque<Sample>& samples) const {
        std::vector<const Sample*> selected;
        selected.reserve(samples.size());
        for (const Sample& sample : samples) {
            selected.push_back(&sample);
        }
        std::sort(selected.begin(), selected.end(), [](const Sample* left, const Sample* right) {
            if (left->quality != right->quality) {
                return left->quality > right->quality;
            }
            if (left->weight() != right->weight()) {
                return left->weight() > right->weight();
            }
            return left->frame_id > right->frame_id;
        });
        if (selected.size() > static_cast<std::size_t>(config.top_k)) {
            selected.resize(static_cast<std::size_t>(config.top_k));
        }
        return selected;
    }

    static bool better_winner(
        const std::pair<const std::string, Aggregate>& candidate,
        const std::pair<const std::string, Aggregate>& winner) {
        if (candidate.second.weight > winner.second.weight + kWeightEpsilon) {
            return true;
        }
        if (std::abs(candidate.second.weight - winner.second.weight) <= kWeightEpsilon) {
            if (candidate.second.count != winner.second.count) {
                return candidate.second.count > winner.second.count;
            }
            if (candidate.second.latest_frame != winner.second.latest_frame) {
                return candidate.second.latest_frame > winner.second.latest_frame;
            }
            return candidate.first < winner.first;
        }
        return false;
    }

    std::optional<PlateFusionResult> compute(int track_id, const TrackHistory& history) const {
        if (history.text_samples.empty() && history.color_samples.empty()) {
            return std::nullopt;
        }

        PlateFusionResult result;
        result.track_id = track_id;
        if (!history.text_samples.empty()) {
            const TextSample& latest = *std::max_element(
                history.text_samples.begin(), history.text_samples.end(),
                [](const TextSample& left, const TextSample& right) {
                    if (left.frame_id != right.frame_id) {
                        return left.frame_id < right.frame_id;
                    }
                    return left.weight() < right.weight();
                });
            result.latest_ocr = latest.ocr;

            const std::vector<const TextSample*> selected =
                top_quality_samples(history.text_samples);
            result.text_sample_count = selected.size();
            std::map<std::string, Aggregate> aggregates;
            double total_weight = 0.0;
            for (const TextSample* sample : selected) {
                Aggregate& aggregate = aggregates[sample->ocr.text];
                aggregate.weight += sample->weight();
                aggregate.quality_sum += sample->quality;
                aggregate.quality_confidence_sum +=
                    static_cast<double>(sample->quality) * sample->ocr.confidence;
                ++aggregate.count;
                aggregate.latest_frame = std::max(aggregate.latest_frame, sample->frame_id);
                total_weight += sample->weight();
            }
            if (!aggregates.empty() && total_weight > kWeightEpsilon) {
                auto winner = aggregates.begin();
                for (auto candidate = std::next(aggregates.begin());
                    candidate != aggregates.end(); ++candidate) {
                    if (better_winner(*candidate, *winner)) {
                        winner = candidate;
                    }
                }
                result.fused_ocr.text = winner->first;
                result.fused_ocr.confidence = winner->second.quality_sum > kWeightEpsilon ?
                    static_cast<float>(winner->second.quality_confidence_sum /
                        winner->second.quality_sum) : 0.0F;
                result.fused_ocr.format_valid = true;
                result.winner_count = winner->second.count;
                result.text_vote_ratio = static_cast<float>(winner->second.weight / total_weight);
                result.stable = result.text_sample_count >=
                        static_cast<std::size_t>(config.min_samples) &&
                    result.winner_count >= static_cast<std::size_t>(config.min_winner_samples) &&
                    result.text_vote_ratio >= config.min_vote_ratio;
                result.fused_ocr.accepted = result.stable;
                if (!result.stable) {
                    result.fused_ocr.rejection_reason = "fusion_unstable";
                }
            }
        }

        if (!history.color_samples.empty()) {
            const std::vector<const ColorSample*> selected =
                top_quality_samples(history.color_samples);
            result.color_sample_count = selected.size();
            std::map<std::string, Aggregate> aggregates;
            double total_weight = 0.0;
            for (const ColorSample* sample : selected) {
                Aggregate& aggregate = aggregates[sample->color.color];
                aggregate.weight += sample->weight();
                aggregate.quality_sum += sample->quality;
                aggregate.quality_confidence_sum +=
                    static_cast<double>(sample->quality) * sample->color.confidence;
                ++aggregate.count;
                aggregate.latest_frame = std::max(aggregate.latest_frame, sample->frame_id);
                total_weight += sample->weight();
            }
            if (!aggregates.empty() && total_weight > kWeightEpsilon) {
                auto winner = aggregates.begin();
                for (auto candidate = std::next(aggregates.begin());
                    candidate != aggregates.end(); ++candidate) {
                    if (better_winner(*candidate, *winner)) {
                        winner = candidate;
                    }
                }
                result.color.color = winner->first;
                result.color.primary_color = winner->first;
                result.color.confidence = winner->second.quality_sum > kWeightEpsilon ?
                    static_cast<float>(winner->second.quality_confidence_sum /
                        winner->second.quality_sum) : 0.0F;
                result.color.primary_confidence = result.color.confidence;
                result.color_vote_ratio = static_cast<float>(winner->second.weight / total_weight);
            }
        }
        return result;
    }

    PlateFusionConfig config;
    std::unordered_map<int, TrackHistory> histories;
};

ConfidenceWeightedPlateFusion::ConfidenceWeightedPlateFusion(const PlateFusionConfig& config)
    : impl_(std::make_unique<Impl>(config)) {}

ConfidenceWeightedPlateFusion::~ConfidenceWeightedPlateFusion() = default;

std::optional<PlateFusionResult> ConfidenceWeightedPlateFusion::update(
    int track_id,
    const PlateFusionObservation& observation) {
    if (track_id <= 0) {
        throw std::invalid_argument("PlateFusion track_id must be positive");
    }
    if (!std::isfinite(observation.quality.quality_score) ||
        observation.quality.quality_score < 0.0F ||
        observation.quality.quality_score > 1.0F) {
        throw std::invalid_argument("PlateFusion quality_score must be finite and within [0, 1]");
    }

    Impl::TrackHistory& history = impl_->histories[track_id];
    if (history.has_last_seen_frame && observation.frame_id < history.last_seen_frame) {
        throw std::invalid_argument("PlateFusion frame_id cannot move backwards for a track");
    }
    history.last_seen_frame = observation.frame_id;
    history.has_last_seen_frame = true;

    const bool valid_quality = observation.quality.acceptable &&
        observation.quality.quality_score >= impl_->config.min_quality_score;
    const bool valid_ocr = valid_quality && observation.ocr.accepted &&
        observation.ocr.format_valid && !observation.ocr.text.empty() &&
        std::isfinite(observation.ocr.confidence) &&
        observation.ocr.confidence >= impl_->config.min_ocr_confidence &&
        observation.ocr.confidence <= 1.0F;
    if (valid_ocr) {
        Impl::TextSample candidate{
            observation.frame_id, observation.quality.quality_score, observation.ocr};
        auto existing = std::find_if(history.text_samples.begin(), history.text_samples.end(),
            [&](const Impl::TextSample& sample) {
                return sample.frame_id == observation.frame_id;
            });
        if (existing == history.text_samples.end()) {
            history.text_samples.push_back(std::move(candidate));
        } else if (candidate.weight() > existing->weight()) {
            *existing = std::move(candidate);
        }
        keep_history_limit(history.text_samples,
            static_cast<std::size_t>(impl_->config.max_history_per_track));
    }

    if (valid_quality && observation.color.has_value()) {
        const ColorResult& color = *observation.color;
        const bool valid_color = !color.color.empty() &&
            (impl_->config.include_other_color || color.color != "other") &&
            std::isfinite(color.confidence) &&
            color.confidence >= impl_->config.min_color_confidence &&
            color.confidence <= 1.0F;
        if (valid_color) {
            Impl::ColorSample candidate{
                observation.frame_id, observation.quality.quality_score, color};
            auto existing = std::find_if(history.color_samples.begin(),
                history.color_samples.end(), [&](const Impl::ColorSample& sample) {
                    return sample.frame_id == observation.frame_id;
                });
            if (existing == history.color_samples.end()) {
                history.color_samples.push_back(std::move(candidate));
            } else if (candidate.weight() > existing->weight()) {
                *existing = std::move(candidate);
            }
            keep_history_limit(history.color_samples,
                static_cast<std::size_t>(impl_->config.max_history_per_track));
        }
    }
    return impl_->compute(track_id, history);
}

std::optional<PlateFusionResult> ConfidenceWeightedPlateFusion::result(int track_id) const {
    const auto history = impl_->histories.find(track_id);
    if (history == impl_->histories.end()) {
        return std::nullopt;
    }
    return impl_->compute(track_id, history->second);
}

void ConfidenceWeightedPlateFusion::prune(std::uint64_t frame_id) {
    for (const auto& [track_id, history] : impl_->histories) {
        (void)track_id;
        if (history.has_last_seen_frame && frame_id < history.last_seen_frame) {
            throw std::invalid_argument("PlateFusion prune frame_id cannot move backwards");
        }
    }
    for (auto history = impl_->histories.begin(); history != impl_->histories.end();) {
        if (history->second.has_last_seen_frame &&
            frame_id - history->second.last_seen_frame >
                static_cast<std::uint64_t>(impl_->config.stale_after_frames)) {
            history = impl_->histories.erase(history);
        } else {
            ++history;
        }
    }
}

void ConfidenceWeightedPlateFusion::reset() {
    impl_->histories.clear();
}

}  // namespace vehicle_system
