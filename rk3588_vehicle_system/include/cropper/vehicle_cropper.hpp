#pragma once

#include "common/config.hpp"
#include "common/types.hpp"

#include <opencv2/core.hpp>
#include <optional>

namespace vehicle_system {

class IVehicleCropper {
public:
    virtual std::optional<VehicleCrop> crop(
        const cv::Mat& frame,
        const Detection& detection) const = 0;

    virtual ~IVehicleCropper() = default;
};

class VehicleCropper final : public IVehicleCropper {
public:
    explicit VehicleCropper(VehicleCropperConfig config);

    std::optional<VehicleCrop> crop(
        const cv::Mat& frame,
        const Detection& detection) const override;

private:
    VehicleCropperConfig config_;
};

}  // namespace vehicle_system
