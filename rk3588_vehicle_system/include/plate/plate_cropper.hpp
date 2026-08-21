#pragma once

#include "common/config.hpp"
#include "common/types.hpp"

#include <opencv2/core.hpp>
#include <optional>

namespace vehicle_system {

class IPlateCropper {
public:
    virtual std::optional<PlateCrop> crop(
        const cv::Mat& vehicle_roi,
        const PlateDetection& detection) const = 0;
    virtual ~IPlateCropper() = default;
};

class PlateCropper final : public IPlateCropper {
public:
    explicit PlateCropper(PlateCropperConfig config);

    std::optional<PlateCrop> crop(
        const cv::Mat& vehicle_roi,
        const PlateDetection& detection) const override;

private:
    PlateCropperConfig config_;
};

}  // namespace vehicle_system
