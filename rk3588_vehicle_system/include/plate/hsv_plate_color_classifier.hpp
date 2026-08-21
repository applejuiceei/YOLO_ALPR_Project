#pragma once

#include "common/config.hpp"
#include "plate/plate_color_classifier.hpp"

namespace vehicle_system {

class HsvPlateColorClassifier final : public IPlateColorClassifier {
public:
    explicit HsvPlateColorClassifier(PlateColorConfig config);

    ColorResult classify(const cv::Mat& plate_roi) override;
    ClassifierTiming last_timing() const override;

private:
    PlateColorConfig config_;
    ClassifierTiming timing_;
};

}  // namespace vehicle_system
