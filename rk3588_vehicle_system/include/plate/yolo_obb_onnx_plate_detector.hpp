#pragma once

#include "common/config.hpp"
#include "plate/plate_detector.hpp"

#include <memory>

namespace vehicle_system {

class YoloObbOnnxPlateDetector final : public IPlateDetector {
public:
    explicit YoloObbOnnxPlateDetector(const PlateDetectorConfig& config);
    ~YoloObbOnnxPlateDetector() override;

    YoloObbOnnxPlateDetector(const YoloObbOnnxPlateDetector&) = delete;
    YoloObbOnnxPlateDetector& operator=(const YoloObbOnnxPlateDetector&) = delete;

    std::vector<PlateDetection> detect(const cv::Mat& vehicle_roi) override;
    DetectorTiming last_timing() const override;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace vehicle_system
