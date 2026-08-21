#pragma once

#include "common/config.hpp"
#include "fusion/plate_fusion.hpp"

#include <memory>

namespace vehicle_system {

class ConfidenceWeightedPlateFusion final : public IPlateFusion {
public:
    explicit ConfidenceWeightedPlateFusion(const PlateFusionConfig& config);
    ~ConfidenceWeightedPlateFusion() override;

    ConfidenceWeightedPlateFusion(const ConfidenceWeightedPlateFusion&) = delete;
    ConfidenceWeightedPlateFusion& operator=(const ConfidenceWeightedPlateFusion&) = delete;

    std::optional<PlateFusionResult> update(
        int track_id,
        const PlateFusionObservation& observation) override;
    std::optional<PlateFusionResult> result(int track_id) const override;
    void prune(std::uint64_t frame_id) override;
    void reset() override;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace vehicle_system
