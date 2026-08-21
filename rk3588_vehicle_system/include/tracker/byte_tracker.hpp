#pragma once

#include "common/config.hpp"
#include "tracker/vehicle_tracker.hpp"

#include <memory>

namespace vehicle_system {

class ByteTracker final : public IVehicleTracker {
public:
    explicit ByteTracker(const TrackerConfig& config);
    ~ByteTracker() override;

    ByteTracker(const ByteTracker&) = delete;
    ByteTracker& operator=(const ByteTracker&) = delete;

    std::vector<TrackedObject> update(
        const std::vector<Detection>& detections,
        std::uint64_t frame_id) override;
    void reset() override;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace vehicle_system
