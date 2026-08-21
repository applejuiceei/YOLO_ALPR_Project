#pragma once

#include "common/config.hpp"
#include "fusion/vehicle_fusion.hpp"

#include <memory>

namespace vehicle_system {

class ConfidenceWeightedVehicleFusion final : public IVehicleFusion {
public:
    explicit ConfidenceWeightedVehicleFusion(const VehicleFusionConfig& config);
    ~ConfidenceWeightedVehicleFusion() override;

    ConfidenceWeightedVehicleFusion(const ConfidenceWeightedVehicleFusion&) = delete;
    ConfidenceWeightedVehicleFusion& operator=(const ConfidenceWeightedVehicleFusion&) = delete;

    std::optional<VehicleFusionResult> update_color(
        int track_id,
        const ColorResult& color,
        std::uint64_t frame_id) override;
    std::optional<VehicleFusionResult> result(int track_id) const override;
    void prune(std::uint64_t frame_id) override;
    void reset() override;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace vehicle_system
