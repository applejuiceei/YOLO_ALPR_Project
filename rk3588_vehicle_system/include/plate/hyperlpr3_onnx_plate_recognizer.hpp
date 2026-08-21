#pragma once

#include "common/config.hpp"
#include "plate/plate_recognizer.hpp"

#include <memory>

namespace vehicle_system {

class HyperLpr3OnnxPlateRecognizer final : public IPlateRecognizer {
public:
    explicit HyperLpr3OnnxPlateRecognizer(const PlateRecognizerConfig& config);
    ~HyperLpr3OnnxPlateRecognizer() override;

    PlateOCRResult recognize(const cv::Mat& plate_roi) override;
    PlateRecognizerTiming last_timing() const override;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace vehicle_system
