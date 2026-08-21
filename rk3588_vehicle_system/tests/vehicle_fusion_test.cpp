#include "fusion/confidence_weighted_vehicle_fusion.hpp"

#include <cmath>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

void require(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

bool near(float left, float right, float tolerance = 1.0e-4F) {
    return std::fabs(left - right) <= tolerance;
}

vehicle_system::ColorResult color(const std::string& name, float confidence) {
    vehicle_system::ColorResult result;
    result.color = name;
    result.confidence = confidence;
    result.primary_color = name;
    result.primary_confidence = confidence;
    return result;
}

}  // namespace

int main() {
    try {
        vehicle_system::VehicleFusionConfig config;
        config.max_history_per_track = 4;
        config.min_samples = 3;
        config.min_sample_confidence = 0.5F;
        config.min_vote_ratio = 0.6F;
        config.stale_after_frames = 5;
        config.include_other = false;
        vehicle_system::ConfidenceWeightedVehicleFusion fusion(config);

        auto result = fusion.update_color(7, color("white", 0.91F), 1);
        require(result.has_value() && result->color.color == "white" && !result->stable,
            "first sample did not create an unstable white candidate");
        result = fusion.update_color(7, color("gray", 0.62F), 2);
        require(result.has_value() && result->color.color == "white" && !result->stable,
            "weighted vote selected the wrong two-sample candidate");
        result = fusion.update_color(7, color("white", 0.95F), 3);
        require(result.has_value() && result->stable && result->sample_count == 3,
            "three-sample result did not become stable");
        require(result->color.color == "white" && near(result->color.confidence, 0.93F),
            "winner confidence is not the mean confidence of white samples");
        require(near(result->vote_ratio, 1.86F / 2.48F),
            "weighted vote ratio is incorrect");

        result = fusion.update_color(7, color("white", 0.89F), 4);
        require(result.has_value() && result->sample_count == 4 &&
            near(result->color.confidence, (0.91F + 0.95F + 0.89F) / 3.0F),
            "four-sample weighted result is incorrect");
        result = fusion.update_color(7, color("other", 0.99F), 5);
        require(result.has_value() && result->sample_count == 4,
            "other color polluted the history");
        result = fusion.update_color(7, color("red", 0.49F), 6);
        require(result.has_value() && result->sample_count == 4,
            "low-confidence color polluted the history");

        result = fusion.update_color(9, color("blue", 0.8F), 2);
        require(result.has_value() && result->track_id == 9 && result->color.color == "blue",
            "track histories are not isolated");

        bool duplicate_rejected = false;
        try {
            fusion.update_color(9, color("blue", 0.9F), 2);
        } catch (const std::invalid_argument&) {
            duplicate_rejected = true;
        }
        require(duplicate_rejected, "duplicate per-track frame was accepted");

        vehicle_system::VehicleFusionConfig rolling_config = config;
        rolling_config.max_history_per_track = 3;
        rolling_config.min_samples = 1;
        vehicle_system::ConfidenceWeightedVehicleFusion rolling(rolling_config);
        rolling.update_color(1, color("red", 0.9F), 1);
        rolling.update_color(1, color("blue", 0.8F), 2);
        rolling.update_color(1, color("blue", 0.8F), 3);
        result = rolling.update_color(1, color("blue", 0.8F), 4);
        require(result.has_value() && result->sample_count == 3 && result->color.color == "blue" &&
            near(result->vote_ratio, 1.0F), "rolling history did not evict the oldest sample");

        fusion.prune(7);
        require(fusion.result(9).has_value(), "active history was pruned too early");
        fusion.prune(8);
        require(!fusion.result(9).has_value(), "stale history was not pruned");
        require(fusion.result(7).has_value(), "newer history was pruned with an older track");

        fusion.reset();
        require(!fusion.result(7).has_value(), "reset did not clear fusion history");

        std::cout << "VehicleFusion tests passed; weighted vote/history/filter/prune/reset verified\n";
        return EXIT_SUCCESS;
    } catch (const std::exception& error) {
        std::cerr << "VehicleFusion test failed: " << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
