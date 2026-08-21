#pragma once

#include "common/types.hpp"

#include <optional>

namespace vehicle_system {

class IPlateRectifier {
public:
    virtual std::optional<RectifiedPlate> rectify(const PlateCrop& plate_crop) const = 0;
    virtual ~IPlateRectifier() = default;
};

}  // namespace vehicle_system
