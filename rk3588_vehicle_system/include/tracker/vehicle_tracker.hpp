#pragma once

#include "common/types.hpp"

#include <cstdint>
#include <vector>

namespace vehicle_system {

class IVehicleTracker {
public:
    virtual std::vector<TrackedObject> update(
        const std::vector<Detection>& detections,
        std::uint64_t frame_id) = 0;

    virtual void reset() = 0;
    virtual ~IVehicleTracker() = default;
};

}  // namespace vehicle_system
