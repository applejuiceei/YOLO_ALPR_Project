#include "tracker/byte_tracker.hpp"

#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace {

void require(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

vehicle_system::Detection detection(
    const cv::Rect& bbox,
    float confidence,
    vehicle_system::ObjectType type = vehicle_system::ObjectType::Car,
    int class_id = 2) {
    vehicle_system::Detection value;
    value.bbox = bbox;
    value.confidence = confidence;
    value.type = type;
    value.class_id = class_id;
    return value;
}

}  // namespace

int main() {
    try {
        vehicle_system::TrackerConfig config;
        config.high_confidence = 0.5F;
        config.low_confidence = 0.1F;
        config.new_track_confidence = 0.5F;
        config.first_match_threshold = 0.8F;
        config.second_match_threshold = 0.5F;
        config.track_buffer_frames = 3;
        config.class_aware = true;
        vehicle_system::ByteTracker tracker(config);

        auto tracks = tracker.update({detection({10, 20, 40, 30}, 0.9F)}, 1);
        require(tracks.size() == 1, "first high-confidence detection did not create a track");
        const int car_id = tracks[0].track_id;
        require(car_id == 1, "first track id is not deterministic");
        require(tracks[0].hits == 1, "new track hit count is incorrect");

        tracks = tracker.update({detection({12, 20, 40, 30}, 0.85F)}, 2);
        require(tracks.size() == 1 && tracks[0].track_id == car_id,
            "high-confidence association changed the track id");

        tracks = tracker.update({detection({14, 20, 40, 30}, 0.2F)}, 3);
        require(tracks.size() == 1 && tracks[0].track_id == car_id,
            "low-confidence second association did not preserve the track id");

        tracks = tracker.update({}, 4);
        require(tracks.empty(), "lost track was emitted without a current detection");
        tracks = tracker.update({detection({18, 20, 40, 30}, 0.9F)}, 5);
        require(tracks.size() == 1 && tracks[0].track_id == car_id,
            "buffered lost track was not reactivated with its original id");

        tracks = tracker.update({
            detection({20, 20, 40, 30}, 0.9F),
            detection({18, 20, 40, 30}, 0.9F, vehicle_system::ObjectType::Person, 0)}, 6);
        require(tracks.size() == 1 && tracks[0].track_id == car_id,
            "tentative person track was published after only one observation");
        tracks = tracker.update({
            detection({22, 20, 40, 30}, 0.9F),
            detection({20, 20, 40, 30}, 0.9F, vehicle_system::ObjectType::Person, 0)}, 7);
        require(tracks.size() == 2 && tracks[0].track_id == car_id &&
            tracks[1].track_id != car_id &&
            tracks[1].type == vehicle_system::ObjectType::Person,
            "class-aware matching merged a person into a vehicle track");

        tracker.update({}, 8);
        tracker.update({}, 9);
        tracker.update({}, 10);
        tracks = tracker.update({detection({30, 20, 40, 30}, 0.9F)}, 11);
        require(tracks.empty(), "new post-expiry track was not kept tentative");
        tracks = tracker.update({detection({32, 20, 40, 30}, 0.9F)}, 12);
        require(tracks.size() == 1 && tracks[0].track_id != car_id,
            "expired vehicle track was incorrectly reused");

        bool rejected_non_monotonic_frame = false;
        try {
            tracker.update({}, 12);
        } catch (const std::invalid_argument&) {
            rejected_non_monotonic_frame = true;
        }
        require(rejected_non_monotonic_frame, "non-monotonic frame id was accepted");

        tracker.reset();
        tracks = tracker.update({detection({0, 0, 20, 20}, 0.9F)}, 0);
        require(tracks.size() == 1 && tracks[0].track_id == 1,
            "reset did not restore the track id state");

        vehicle_system::ByteTracker second_camera_tracker(config);
        tracks = second_camera_tracker.update({detection({0, 0, 20, 20}, 0.9F)}, 100);
        require(tracks.size() == 1 && tracks[0].track_id == 1,
            "separate tracker instances did not maintain independent camera id spaces");

        std::cout << "ByteTracker tests passed; high/low/reactivation/class/expiry/reset verified\n";
        return EXIT_SUCCESS;
    } catch (const std::exception& error) {
        std::cerr << "ByteTracker test failed: " << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
