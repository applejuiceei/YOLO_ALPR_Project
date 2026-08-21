#pragma once

#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <opencv2/core.hpp>
#include <optional>
#include <string>

namespace vehicle_system {

enum class ObjectType {
    Person,
    Car,
    Bus,
    Truck,
    NonMotor,
    Unknown,
};

struct Detection {
    int class_id = -1;
    float confidence = 0.0F;
    cv::Rect bbox;
    ObjectType type = ObjectType::Unknown;
};

struct VehicleCrop {
    cv::Rect source_bbox;
    cv::Mat roi;
};

struct ColorResult {
    std::string color = "other";
    float confidence = 0.0F;
    std::string primary_color = "other";
    float primary_confidence = 0.0F;
    std::string secondary_color;
    float secondary_confidence = 0.0F;
    std::string model_color;
};

struct TrackedObject {
    int track_id = -1;
    int class_id = -1;
    float confidence = 0.0F;
    cv::Rect bbox;
    ObjectType type = ObjectType::Unknown;
    int age = 0;
    int hits = 0;
};

struct VehicleFusionResult {
    int track_id = -1;
    ColorResult color;
    std::size_t sample_count = 0;
    float vote_ratio = 0.0F;
    bool stable = false;
};

struct PlateDetection {
    cv::Rect bbox;
    std::array<cv::Point2f, 4> corners{};
    float confidence = 0.0F;
    float angle_radians = 0.0F;
};

struct PlateCrop {
    cv::Rect source_bbox;
    std::array<cv::Point2f, 4> corners{};
    cv::Mat roi;
};

struct PlateQuality {
    float blur_score = 0.0F;
    float brightness = 0.0F;
    float contrast = 0.0F;
    float size_score = 0.0F;
    float sharpness_score = 0.0F;
    float exposure_score = 0.0F;
    float contrast_score = 0.0F;
    float quality_score = 0.0F;
    bool acceptable = false;
    std::string rejection_reason;
};

enum class PlateRectificationMethod {
    Resize,
    Perspective,
    ResizeFallback,
};

struct RectifiedPlate {
    cv::Mat image;
    std::array<cv::Point2f, 4> ordered_source_corners{};
    PlateRectificationMethod method = PlateRectificationMethod::Resize;
};

struct PlateOCRResult {
    std::string text;
    float confidence = 0.0F;
    bool format_valid = false;
    bool accepted = false;
    std::string rejection_reason;
};

struct PlateFusionObservation {
    std::uint64_t frame_id = 0;
    PlateQuality quality;
    PlateOCRResult ocr;
    std::optional<ColorResult> color;
};

struct PlateFusionResult {
    int track_id = -1;
    PlateOCRResult latest_ocr;
    PlateOCRResult fused_ocr;
    ColorResult color;
    std::size_t text_sample_count = 0;
    std::size_t winner_count = 0;
    std::size_t color_sample_count = 0;
    float text_vote_ratio = 0.0F;
    float color_vote_ratio = 0.0F;
    bool stable = false;
};

struct PlateRecognizerTiming {
    double preprocess_ms = 0.0;
    double inference_ms = 0.0;
    double decode_ms = 0.0;

    double total_ms() const {
        return preprocess_ms + inference_ms + decode_ms;
    }
};

struct FramePacket {
    int camera_id = 0;
    int lane_id = 0;
    std::uint64_t frame_id = 0;
    std::chrono::system_clock::time_point timestamp;
    cv::Mat frame;
};

struct DetectorTiming {
    double preprocess_ms = 0.0;
    double inference_ms = 0.0;
    double postprocess_ms = 0.0;

    double total_ms() const {
        return preprocess_ms + inference_ms + postprocess_ms;
    }
};

struct ClassifierTiming {
    double preprocess_ms = 0.0;
    double inference_ms = 0.0;
    double postprocess_ms = 0.0;

    double total_ms() const {
        return preprocess_ms + inference_ms + postprocess_ms;
    }
};

ObjectType object_type_from_coco(int class_id);
const char* object_type_name(ObjectType type);

}  // namespace vehicle_system
