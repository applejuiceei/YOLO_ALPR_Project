#include "tracker/byte_tracker.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <memory>
#include <numeric>
#include <opencv2/video/tracking.hpp>
#include <stdexcept>
#include <utility>
#include <vector>

namespace vehicle_system {
namespace {

enum class TrackState {
    Tentative,
    Tracked,
    Lost,
};

struct MatchResult {
    std::vector<std::pair<std::size_t, std::size_t>> matches;
    std::vector<std::size_t> unmatched_rows;
    std::vector<std::size_t> unmatched_columns;
};

float intersection_over_union(const cv::Rect2f& left, const cv::Rect& right) {
    const float x1 = std::max(left.x, static_cast<float>(right.x));
    const float y1 = std::max(left.y, static_cast<float>(right.y));
    const float x2 = std::min(left.x + left.width, static_cast<float>(right.x + right.width));
    const float y2 = std::min(left.y + left.height, static_cast<float>(right.y + right.height));
    const float intersection = std::max(0.0F, x2 - x1) * std::max(0.0F, y2 - y1);
    const float union_area = left.area() + static_cast<float>(right.area()) - intersection;
    return union_area > 0.0F ? intersection / union_area : 0.0F;
}

int compatibility_group(ObjectType type) {
    switch (type) {
        case ObjectType::Car:
        case ObjectType::Bus:
        case ObjectType::Truck:
            return 1;
        case ObjectType::NonMotor:
            return 2;
        case ObjectType::Person:
            return 3;
        default:
            return 4;
    }
}

bool compatible(const TrackedObject& track, const Detection& detection, bool class_aware) {
    if (!class_aware) {
        return true;
    }
    const int track_group = compatibility_group(track.type);
    const int detection_group = compatibility_group(detection.type);
    if (track_group != detection_group) {
        return false;
    }
    if (track_group == 4) {
        return track.class_id == detection.class_id;
    }
    return true;
}

std::vector<int> hungarian(const std::vector<std::vector<float>>& costs) {
    const std::size_t rows = costs.size();
    const std::size_t columns = rows == 0 ? 0 : costs.front().size();
    const std::size_t dimension = std::max(rows, columns);
    if (dimension == 0) {
        return {};
    }

    std::vector<std::vector<double>> square(
        dimension, std::vector<double>(dimension, 1.0));
    for (std::size_t row = 0; row < rows; ++row) {
        for (std::size_t column = 0; column < columns; ++column) {
            square[row][column] = static_cast<double>(costs[row][column]);
        }
    }

    std::vector<double> row_potential(dimension + 1, 0.0);
    std::vector<double> column_potential(dimension + 1, 0.0);
    std::vector<std::size_t> column_match(dimension + 1, 0);
    std::vector<std::size_t> previous_column(dimension + 1, 0);

    for (std::size_t row = 1; row <= dimension; ++row) {
        column_match[0] = row;
        std::size_t current_column = 0;
        std::vector<double> minimum(dimension + 1, std::numeric_limits<double>::infinity());
        std::vector<bool> used(dimension + 1, false);
        do {
            used[current_column] = true;
            const std::size_t current_row = column_match[current_column];
            double delta = std::numeric_limits<double>::infinity();
            std::size_t next_column = 0;
            for (std::size_t column = 1; column <= dimension; ++column) {
                if (used[column]) {
                    continue;
                }
                const double reduced = square[current_row - 1][column - 1] -
                    row_potential[current_row] - column_potential[column];
                if (reduced < minimum[column]) {
                    minimum[column] = reduced;
                    previous_column[column] = current_column;
                }
                if (minimum[column] < delta) {
                    delta = minimum[column];
                    next_column = column;
                }
            }
            for (std::size_t column = 0; column <= dimension; ++column) {
                if (used[column]) {
                    row_potential[column_match[column]] += delta;
                    column_potential[column] -= delta;
                } else {
                    minimum[column] -= delta;
                }
            }
            current_column = next_column;
        } while (column_match[current_column] != 0);

        do {
            const std::size_t next_column = previous_column[current_column];
            column_match[current_column] = column_match[next_column];
            current_column = next_column;
        } while (current_column != 0);
    }

    std::vector<int> assignment(rows, -1);
    for (std::size_t column = 1; column <= dimension; ++column) {
        const std::size_t row = column_match[column];
        if (row >= 1 && row <= rows && column <= columns) {
            assignment[row - 1] = static_cast<int>(column - 1);
        }
    }
    return assignment;
}

MatchResult linear_assignment(
    const std::vector<std::vector<float>>& costs,
    std::size_t column_count,
    float maximum_cost) {
    MatchResult result;
    const std::size_t rows = costs.size();
    const std::size_t columns = column_count;
    if (rows == 0) {
        result.unmatched_columns.resize(columns);
        std::iota(result.unmatched_columns.begin(), result.unmatched_columns.end(), 0);
        return result;
    }
    if (columns == 0) {
        result.unmatched_rows.resize(rows);
        std::iota(result.unmatched_rows.begin(), result.unmatched_rows.end(), 0);
        return result;
    }

    const std::vector<int> assignment = hungarian(costs);
    std::vector<bool> matched_columns(columns, false);
    for (std::size_t row = 0; row < rows; ++row) {
        const int column = assignment[row];
        if (column >= 0 && static_cast<std::size_t>(column) < columns &&
            costs[row][static_cast<std::size_t>(column)] <= maximum_cost) {
            result.matches.emplace_back(row, static_cast<std::size_t>(column));
            matched_columns[static_cast<std::size_t>(column)] = true;
        } else {
            result.unmatched_rows.push_back(row);
        }
    }
    for (std::size_t column = 0; column < columns; ++column) {
        if (!matched_columns[column]) {
            result.unmatched_columns.push_back(column);
        }
    }
    return result;
}

cv::Vec4f measurement_from_bbox(const cv::Rect& bbox) {
    const float height = static_cast<float>(std::max(1, bbox.height));
    const float width = static_cast<float>(std::max(1, bbox.width));
    return {
        static_cast<float>(bbox.x) + width * 0.5F,
        static_cast<float>(bbox.y) + height * 0.5F,
        width / height,
        height};
}

cv::Rect2f bbox_from_state(const cv::Mat& state) {
    const float center_x = state.at<float>(0);
    const float center_y = state.at<float>(1);
    const float aspect = std::max(0.01F, state.at<float>(2));
    const float height = std::max(1.0F, state.at<float>(3));
    const float width = std::max(1.0F, aspect * height);
    return {center_x - width * 0.5F, center_y - height * 0.5F, width, height};
}

cv::Rect rounded_bbox(const cv::Rect2f& bbox) {
    return {
        static_cast<int>(std::lround(bbox.x)),
        static_cast<int>(std::lround(bbox.y)),
        std::max(1, static_cast<int>(std::lround(bbox.width))),
        std::max(1, static_cast<int>(std::lround(bbox.height)))};
}

}  // namespace

struct ByteTracker::Impl {
    struct Track {
        Track(int assigned_id, const Detection& detection, std::uint64_t frame_id, bool activated)
            : object(), kalman(8, 4, 0, CV_32F),
              state(activated ? TrackState::Tracked : TrackState::Tentative),
              start_frame(frame_id), last_observed_frame(frame_id), state_frame(frame_id) {
            object.track_id = assigned_id;
            object.class_id = detection.class_id;
            object.confidence = detection.confidence;
            object.bbox = detection.bbox;
            object.type = detection.type;
            object.age = 1;
            object.hits = 1;

            cv::setIdentity(kalman.transitionMatrix);
            kalman.measurementMatrix = cv::Mat::zeros(4, 8, CV_32F);
            for (int index = 0; index < 4; ++index) {
                kalman.measurementMatrix.at<float>(index, index) = 1.0F;
            }
            cv::setIdentity(kalman.processNoiseCov, cv::Scalar::all(1.0e-2));
            cv::setIdentity(kalman.measurementNoiseCov, cv::Scalar::all(1.0e-1));
            cv::setIdentity(kalman.errorCovPost, cv::Scalar::all(1.0));
            kalman.statePost = cv::Mat::zeros(8, 1, CV_32F);
            const cv::Vec4f measurement = measurement_from_bbox(detection.bbox);
            for (int index = 0; index < 4; ++index) {
                kalman.statePost.at<float>(index) = measurement[index];
            }
        }

        void predict(std::uint64_t frame_id) {
            const float delta = static_cast<float>(std::max<std::uint64_t>(1, frame_id - state_frame));
            cv::setIdentity(kalman.transitionMatrix);
            for (int index = 0; index < 4; ++index) {
                kalman.transitionMatrix.at<float>(index, index + 4) = delta;
            }
            cv::setIdentity(kalman.processNoiseCov, cv::Scalar::all(1.0e-2F * delta));
            const cv::Mat prediction = kalman.predict();
            predicted_bbox = bbox_from_state(prediction);
            state_frame = frame_id;
        }

        void update(const Detection& detection, std::uint64_t frame_id) {
            cv::Mat measurement(4, 1, CV_32F);
            const cv::Vec4f values = measurement_from_bbox(detection.bbox);
            for (int index = 0; index < 4; ++index) {
                measurement.at<float>(index) = values[index];
            }
            const cv::Mat corrected = kalman.correct(measurement);
            predicted_bbox = bbox_from_state(corrected);
            object.class_id = detection.class_id;
            object.confidence = detection.confidence;
            object.bbox = rounded_bbox(predicted_bbox);
            object.type = detection.type;
            object.hits += 1;
            object.age = static_cast<int>(std::min<std::uint64_t>(
                frame_id - start_frame + 1, static_cast<std::uint64_t>(std::numeric_limits<int>::max())));
            state = TrackState::Tracked;
            last_observed_frame = frame_id;
            state_frame = frame_id;
        }

        TrackedObject object;
        cv::KalmanFilter kalman;
        TrackState state;
        std::uint64_t start_frame;
        std::uint64_t last_observed_frame;
        std::uint64_t state_frame;
        cv::Rect2f predicted_bbox;
        bool removed = false;
    };

    explicit Impl(const TrackerConfig& tracker_config) : config(tracker_config) {
        if (config.low_confidence < 0.0F || config.high_confidence > 1.0F ||
            config.low_confidence >= config.high_confidence) {
            throw std::invalid_argument("ByteTrack requires 0 <= low_confidence < high_confidence <= 1");
        }
        if (config.new_track_confidence < config.high_confidence || config.new_track_confidence > 1.0F) {
            throw std::invalid_argument("ByteTrack new_track_confidence must be within [high_confidence, 1]");
        }
        if (config.first_match_threshold < 0.0F || config.first_match_threshold > 1.0F ||
            config.second_match_threshold < 0.0F || config.second_match_threshold > 1.0F ||
            config.unconfirmed_match_threshold < 0.0F || config.unconfirmed_match_threshold > 1.0F) {
            throw std::invalid_argument("ByteTrack match thresholds must be within [0, 1]");
        }
        if (config.track_buffer_frames < 0) {
            throw std::invalid_argument("ByteTrack track_buffer_frames must be non-negative");
        }
    }

    std::vector<std::vector<float>> costs(
        const std::vector<Track*>& track_candidates,
        const std::vector<const Detection*>& detections,
        bool fuse_score) const {
        std::vector<std::vector<float>> result(
            track_candidates.size(), std::vector<float>(detections.size(), 1000.0F));
        for (std::size_t row = 0; row < track_candidates.size(); ++row) {
            for (std::size_t column = 0; column < detections.size(); ++column) {
                if (!compatible(track_candidates[row]->object, *detections[column], config.class_aware)) {
                    continue;
                }
                float similarity = intersection_over_union(
                    track_candidates[row]->predicted_bbox, detections[column]->bbox);
                if (fuse_score) {
                    similarity *= detections[column]->confidence;
                }
                result[row][column] = 1.0F - similarity;
            }
        }
        return result;
    }

    TrackerConfig config;
    std::vector<std::unique_ptr<Track>> tracks;
    int next_track_id = 1;
    bool has_last_frame = false;
    std::uint64_t last_frame = 0;
};

ByteTracker::ByteTracker(const TrackerConfig& config)
    : impl_(std::make_unique<Impl>(config)) {}

ByteTracker::~ByteTracker() = default;

std::vector<TrackedObject> ByteTracker::update(
    const std::vector<Detection>& detections,
    std::uint64_t frame_id) {
    if (impl_->has_last_frame && frame_id <= impl_->last_frame) {
        throw std::invalid_argument("ByteTracker frame_id must be strictly increasing");
    }
    const bool first_update = !impl_->has_last_frame;
    impl_->has_last_frame = true;
    impl_->last_frame = frame_id;

    impl_->tracks.erase(
        std::remove_if(impl_->tracks.begin(), impl_->tracks.end(), [&](const auto& track) {
            return frame_id - track->last_observed_frame >
                static_cast<std::uint64_t>(impl_->config.track_buffer_frames);
        }),
        impl_->tracks.end());

    std::vector<const Detection*> high_detections;
    std::vector<const Detection*> low_detections;
    for (const Detection& detection : detections) {
        if (detection.bbox.width <= 0 || detection.bbox.height <= 0 ||
            !std::isfinite(detection.confidence) || detection.confidence < impl_->config.low_confidence) {
            continue;
        }
        if (detection.confidence >= impl_->config.high_confidence) {
            high_detections.push_back(&detection);
        } else {
            low_detections.push_back(&detection);
        }
    }

    std::vector<Impl::Track*> track_pool;
    std::vector<Impl::Track*> tentative_tracks;
    for (const std::unique_ptr<Impl::Track>& track : impl_->tracks) {
        track->predict(frame_id);
        if (track->state == TrackState::Tentative) {
            tentative_tracks.push_back(track.get());
        } else {
            track_pool.push_back(track.get());
        }
    }

    const MatchResult first = linear_assignment(
        impl_->costs(track_pool, high_detections, true), high_detections.size(),
        impl_->config.first_match_threshold);
    for (const auto& [track_index, detection_index] : first.matches) {
        track_pool[track_index]->update(*high_detections[detection_index], frame_id);
    }

    std::vector<Impl::Track*> second_pool;
    for (std::size_t unmatched_index : first.unmatched_rows) {
        if (track_pool[unmatched_index]->state == TrackState::Tracked) {
            second_pool.push_back(track_pool[unmatched_index]);
        }
    }
    const MatchResult second = linear_assignment(
        impl_->costs(second_pool, low_detections, false), low_detections.size(),
        impl_->config.second_match_threshold);
    for (const auto& [track_index, detection_index] : second.matches) {
        second_pool[track_index]->update(*low_detections[detection_index], frame_id);
    }
    for (std::size_t unmatched_index : second.unmatched_rows) {
        second_pool[unmatched_index]->state = TrackState::Lost;
    }

    std::vector<const Detection*> remaining_high_detections;
    std::vector<std::size_t> remaining_high_indices;
    for (std::size_t detection_index : first.unmatched_columns) {
        remaining_high_detections.push_back(high_detections[detection_index]);
        remaining_high_indices.push_back(detection_index);
    }
    const MatchResult tentative_matches = linear_assignment(
        impl_->costs(tentative_tracks, remaining_high_detections, true),
        remaining_high_detections.size(), impl_->config.unconfirmed_match_threshold);
    for (const auto& [track_index, detection_index] : tentative_matches.matches) {
        tentative_tracks[track_index]->update(*remaining_high_detections[detection_index], frame_id);
    }
    for (std::size_t unmatched_index : tentative_matches.unmatched_rows) {
        tentative_tracks[unmatched_index]->removed = true;
    }

    for (std::size_t remaining_index : tentative_matches.unmatched_columns) {
        const std::size_t detection_index = remaining_high_indices[remaining_index];
        const Detection& detection = *high_detections[detection_index];
        if (detection.confidence >= impl_->config.new_track_confidence) {
            impl_->tracks.push_back(std::make_unique<Impl::Track>(
                impl_->next_track_id++, detection, frame_id, first_update));
        }
    }

    impl_->tracks.erase(
        std::remove_if(impl_->tracks.begin(), impl_->tracks.end(), [&](const auto& track) {
            return track->removed;
        }),
        impl_->tracks.end());

    std::vector<TrackedObject> output;
    for (const std::unique_ptr<Impl::Track>& track : impl_->tracks) {
        if (track->state == TrackState::Tracked && track->last_observed_frame == frame_id) {
            output.push_back(track->object);
        }
    }
    std::sort(output.begin(), output.end(), [](const TrackedObject& left, const TrackedObject& right) {
        return left.track_id < right.track_id;
    });
    return output;
}

void ByteTracker::reset() {
    impl_->tracks.clear();
    impl_->next_track_id = 1;
    impl_->has_last_frame = false;
    impl_->last_frame = 0;
}

}  // namespace vehicle_system
