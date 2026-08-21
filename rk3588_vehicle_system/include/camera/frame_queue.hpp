#pragma once

#include "common/types.hpp"

#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <mutex>

namespace vehicle_system {

class FrameQueue {
public:
    explicit FrameQueue(std::size_t capacity) : capacity_(capacity == 0 ? 1 : capacity) {}

    void push(FramePacket packet) {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (closed_) {
                return;
            }
            if (queue_.size() >= capacity_) {
                queue_.pop_front();
                ++dropped_;
            }
            queue_.push_back(std::move(packet));
        }
        condition_.notify_one();
    }

    bool wait_pop(FramePacket& packet) {
        std::unique_lock<std::mutex> lock(mutex_);
        condition_.wait(lock, [this] { return closed_ || !queue_.empty(); });
        if (queue_.empty()) {
            return false;
        }
        packet = std::move(queue_.front());
        queue_.pop_front();
        return true;
    }

    void close() {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            closed_ = true;
        }
        condition_.notify_all();
    }

    std::uint64_t dropped() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return dropped_;
    }

private:
    const std::size_t capacity_;
    mutable std::mutex mutex_;
    std::condition_variable condition_;
    std::deque<FramePacket> queue_;
    std::uint64_t dropped_ = 0;
    bool closed_ = false;
};

}  // namespace vehicle_system

