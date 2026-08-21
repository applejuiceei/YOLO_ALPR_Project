#pragma once

#include "common/config.hpp"
#include "plate/plate_quality_evaluator.hpp"

namespace vehicle_system {

class OpenCvPlateQualityEvaluator final : public IPlateQualityEvaluator {
public:
    explicit OpenCvPlateQualityEvaluator(PlateQualityConfig config);
    PlateQuality evaluate(const cv::Mat& plate_roi) const override;

private:
    PlateQualityConfig config_;
    float weight_sum_ = 1.0F;
};

}  // namespace vehicle_system
