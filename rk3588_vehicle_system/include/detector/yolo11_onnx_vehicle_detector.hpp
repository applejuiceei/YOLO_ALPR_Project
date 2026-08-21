#pragma once

#include "common/config.hpp"
#include "detector/vehicle_detector.hpp"

#include <memory>

namespace vehicle_system {

class Yolo11OnnxVehicleDetector final : public IVehicleDetector {
public:
    explicit Yolo11OnnxVehicleDetector(const DetectorConfig& config);
    ~Yolo11OnnxVehicleDetector() override;

    Yolo11OnnxVehicleDetector(const Yolo11OnnxVehicleDetector&) = delete;
    Yolo11OnnxVehicleDetector& operator=(const Yolo11OnnxVehicleDetector&) = delete;

    std::vector<Detection> detect(const cv::Mat& frame) override;
    DetectorTiming last_timing() const override;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace vehicle_system

