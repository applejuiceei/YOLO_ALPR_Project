#include "fusion/confidence_weighted_plate_fusion.hpp"

#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

vehicle_system::PlateFusionObservation observation(
    std::uint64_t frame_id,
    const std::string& text,
    float ocr_confidence,
    float quality,
    bool accepted = true,
    const std::string& color = "blue",
    float color_confidence = 0.9F) {
    vehicle_system::PlateFusionObservation value;
    value.frame_id = frame_id;
    value.quality.acceptable = true;
    value.quality.quality_score = quality;
    value.ocr.text = text;
    value.ocr.confidence = ocr_confidence;
    value.ocr.format_valid = accepted;
    value.ocr.accepted = accepted;
    vehicle_system::ColorResult color_result;
    color_result.color = color;
    color_result.confidence = color_confidence;
    value.color = color_result;
    return value;
}

void require(bool condition, const std::string& message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

}  // namespace

int main() {
    try {
        vehicle_system::PlateFusionConfig config;
        config.max_history_per_track = 5;
        config.top_k = 3;
        config.min_samples = 3;
        config.min_winner_samples = 2;
        config.min_vote_ratio = 0.50F;
        config.stale_after_frames = 10;
        vehicle_system::ConfidenceWeightedPlateFusion fusion(config);

        auto result = fusion.update(1, observation(1, "冀A12345", 0.90F, 0.90F));
        require(result.has_value() && !result->stable, "one sample must be unstable");
        require(result->latest_ocr.text == "冀A12345", "latest accepted OCR missing");

        fusion.update(1, observation(2, "冀A1234S", 0.80F, 0.60F));
        result = fusion.update(1, observation(3, "冀A12345", 0.85F, 0.80F));
        require(result.has_value() && result->stable, "weighted majority must become stable");
        require(result->fused_ocr.text == "冀A12345", "correct weighted winner not selected");
        require(result->winner_count == 2 && result->text_sample_count == 3,
            "winner/sample counts are incorrect");
        require(result->text_vote_ratio > 0.70F, "weighted vote ratio is too low");
        require(result->color.color == "blue", "plate color fusion failed");

        auto rejected = observation(4, "京B00000", 0.99F, 0.99F, false);
        result = fusion.update(1, rejected);
        require(result->latest_ocr.text == "冀A12345",
            "rejected OCR must not replace latest accepted OCR");

        fusion.update(1, observation(5, "粤C11111", 0.60F, 0.50F));
        result = fusion.update(1, observation(5, "冀A12345", 0.95F, 0.95F));
        require(result->latest_ocr.text == "冀A12345",
            "higher-weight same-frame OCR must replace lower-weight OCR");

        fusion.update(1, observation(6, "鲁D22222", 0.70F, 0.51F));
        require(fusion.result(1)->text_sample_count == 3,
            "top-k must limit samples used in voting");

        auto other_color = observation(7, "冀A12345", 0.90F, 0.90F, true, "other", 1.0F);
        result = fusion.update(1, other_color);
        require(result->color.color == "blue", "other color must be excluded by default");

        auto track_two = fusion.update(2, observation(8, "豫J12345", 0.95F, 0.95F));
        require(track_two->latest_ocr.text == "豫J12345", "track isolation failed");
        require(fusion.result(1)->latest_ocr.text != fusion.result(2)->latest_ocr.text,
            "tracks unexpectedly share history");

        bool backward_rejected = false;
        try {
            fusion.update(2, observation(7, "豫J12345", 0.95F, 0.95F));
        } catch (const std::invalid_argument&) {
            backward_rejected = true;
        }
        require(backward_rejected, "backward frame must be rejected");

        fusion.prune(18);
        require(!fusion.result(1).has_value() && fusion.result(2).has_value(),
            "stale pruning boundary is incorrect");
        fusion.prune(19);
        require(!fusion.result(2).has_value(), "stale track was not pruned");
        fusion.reset();

        std::cout << "PlateFusion tests passed; weighted vote/top-k/dedup/filter/prune verified\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "PlateFusion test failed: " << error.what() << '\n';
        return 1;
    }
}
