#pragma once

#include "common/types.hpp"

#include <cstdint>
#include <optional>

namespace vehicle_system {

class IPlateFusion {
public:
    virtual std::optional<PlateFusionResult> update(
        int track_id,
        const PlateFusionObservation& observation) = 0;
    virtual std::optional<PlateFusionResult> result(int track_id) const = 0;
    virtual void prune(std::uint64_t frame_id) = 0;
    virtual void reset() = 0;
    virtual ~IPlateFusion() = default;
};

}  // namespace vehicle_system
