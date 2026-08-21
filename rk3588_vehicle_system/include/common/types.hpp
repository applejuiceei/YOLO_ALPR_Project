#pragma once

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <opencv2/core.hpp>
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
