#include "fusion/confidence_weighted_vehicle_fusion.hpp"

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

namespace vehicle_system {

struct ConfidenceWeightedVehicleFusion::Impl {
    struct Sample {
        std::string color;
        float confidence = 0.0F;
    };

    struct TrackHistory {
        std::deque<Sample> samples;
        std::uint64_t last_seen_frame = 0;
        bool has_last_seen_frame = false;
    };

    struct Aggregate {
        double weight = 0.0;
        std::size_t count = 0;
    };

    explicit Impl(const VehicleFusionConfig& fusion_config) : config(fusion_config) {
        if (config.max_history_per_track <= 0) {
            throw std::invalid_argument("VehicleFusion max_history_per_track must be positive");
        }
        if (config.min_samples <= 0 || config.min_samples > config.max_history_per_track) {
            throw std::invalid_argument(
                "VehicleFusion min_samples must be within [1, max_history_per_track]");
        }
        if (config.min_sample_confidence < 0.0F || config.min_sample_confidence > 1.0F ||
            config.min_vote_ratio < 0.0F || config.min_vote_ratio > 1.0F) {
            throw std::invalid_argument("VehicleFusion confidence thresholds must be within [0, 1]");
        }
        if (config.stale_after_frames < 0) {
            throw std::invalid_argument("VehicleFusion stale_after_frames must be non-negative");
        }
    }

    std::optional<VehicleFusionResult> compute(int track_id, const TrackHistory& history) const {
        if (history.samples.empty()) {
            return std::nullopt;
        }

        std::map<std::string, Aggregate> aggregates;
        double total_weight = 0.0;
        for (const Sample& sample : history.samples) {
            Aggregate& aggregate = aggregates[sample.color];
            aggregate.weight += sample.confidence;
            ++aggregate.count;
            total_weight += sample.confidence;
        }
        if (aggregates.empty() || total_weight <= std::numeric_limits<double>::epsilon()) {
            return std::nullopt;
        }

        auto winner = aggregates.begin();
        for (auto current = std::next(aggregates.begin()); current != aggregates.end(); ++current) {
            if (current->second.weight > winner->second.weight ||
                (current->second.weight == winner->second.weight &&
                    current->second.count > winner->second.count)) {
                winner = current;
            }
        }

        VehicleFusionResult result;
        result.track_id = track_id;
        result.sample_count = history.samples.size();
        result.vote_ratio = static_cast<float>(winner->second.weight / total_weight);
        result.stable = result.sample_count >= static_cast<std::size_t>(config.min_samples) &&
            result.vote_ratio >= config.min_vote_ratio;
        result.color.color = winner->first;
        result.color.confidence = static_cast<float>(
            winner->second.weight / static_cast<double>(winner->second.count));
        result.color.primary_color = result.color.color;
        result.color.primary_confidence = result.color.confidence;
        return result;
    }

    VehicleFusionConfig config;
    std::unordered_map<int, TrackHistory> histories;
};

ConfidenceWeightedVehicleFusion::ConfidenceWeightedVehicleFusion(const VehicleFusionConfig& config)
    : impl_(std::make_unique<Impl>(config)) {}

ConfidenceWeightedVehicleFusion::~ConfidenceWeightedVehicleFusion() = default;

std::optional<VehicleFusionResult> ConfidenceWeightedVehicleFusion::update_color(
    int track_id,
    const ColorResult& color,
    std::uint64_t frame_id) {
    if (track_id <= 0) {
        throw std::invalid_argument("VehicleFusion track_id must be positive");
    }

    Impl::TrackHistory& history = impl_->histories[track_id];
    if (history.has_last_seen_frame && frame_id <= history.last_seen_frame) {
        throw std::invalid_argument("VehicleFusion frame_id must increase for each track");
    }
    history.last_seen_frame = frame_id;
    history.has_last_seen_frame = true;

    const bool valid_confidence = std::isfinite(color.confidence) && color.confidence > 0.0F &&
        color.confidence >= impl_->config.min_sample_confidence;
    const bool valid_color = !color.color.empty() &&
        (impl_->config.include_other || color.color != "other");
    if (valid_confidence && valid_color) {
        history.samples.push_back({color.color, color.confidence});
        while (history.samples.size() >
            static_cast<std::size_t>(impl_->config.max_history_per_track)) {
            history.samples.pop_front();
        }
    }
    return impl_->compute(track_id, history);
}

std::optional<VehicleFusionResult> ConfidenceWeightedVehicleFusion::result(int track_id) const {
    const auto history = impl_->histories.find(track_id);
    if (history == impl_->histories.end()) {
        return std::nullopt;
    }
    return impl_->compute(track_id, history->second);
}

void ConfidenceWeightedVehicleFusion::prune(std::uint64_t frame_id) {
    for (const auto& [track_id, history] : impl_->histories) {
        (void)track_id;
        if (history.has_last_seen_frame && frame_id < history.last_seen_frame) {
            throw std::invalid_argument("VehicleFusion prune frame_id cannot move backwards");
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

void ConfidenceWeightedVehicleFusion::reset() {
    impl_->histories.clear();
}

}  // namespace vehicle_system
