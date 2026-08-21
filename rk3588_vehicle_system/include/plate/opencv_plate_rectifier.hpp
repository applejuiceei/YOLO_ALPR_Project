#pragma once

#include "common/config.hpp"
#include "plate/plate_rectifier.hpp"

namespace vehicle_system {

class OpenCvPlateRectifier final : public IPlateRectifier {
public:
    explicit OpenCvPlateRectifier(PlateRectifierConfig config);
    std::optional<RectifiedPlate> rectify(const PlateCrop& plate_crop) const override;

private:
    std::optional<RectifiedPlate> resize_only(
        const PlateCrop& plate_crop,
        PlateRectificationMethod method) const;
    std::optional<std::array<cv::Point2f, 4>> order_corners(
        const PlateCrop& plate_crop) const;

    PlateRectifierConfig config_;
};

}  // namespace vehicle_system
