#pragma once

#include "classifier/vehicle_color_classifier.hpp"
#include "common/config.hpp"

#include <memory>

namespace vehicle_system {

class PpVehicleOnnxColorClassifier final : public IVehicleColorClassifier {
public:
    explicit PpVehicleOnnxColorClassifier(const VehicleColorConfig& config);
    ~PpVehicleOnnxColorClassifier() override;

    PpVehicleOnnxColorClassifier(const PpVehicleOnnxColorClassifier&) = delete;
    PpVehicleOnnxColorClassifier& operator=(const PpVehicleOnnxColorClassifier&) = delete;

    ColorResult classify(const cv::Mat& vehicle_roi) override;
    ClassifierTiming last_timing() const override;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace vehicle_system
