#pragma once

#include "common/types.hpp"

#include <cstdint>
#include <optional>

namespace vehicle_system {

class IVehicleFusion {
public:
    virtual std::optional<VehicleFusionResult> update_color(
        int track_id,
        const ColorResult& color,
        std::uint64_t frame_id) = 0;

    virtual std::optional<VehicleFusionResult> result(int track_id) const = 0;
    virtual void prune(std::uint64_t frame_id) = 0;
    virtual void reset() = 0;
    virtual ~IVehicleFusion() = default;
};

}  // namespace vehicle_system
