#pragma once

#include "common/config.hpp"

#include <cstdint>
#include <memory>
#include <opencv2/core.hpp>
#include <string>
#include <vector>

namespace vehicle_system {

std::vector<std::uint16_t> utf8_to_utf16(const std::string& utf8);
void configure_utf8_console();

class IUtf8TextRenderer {
public:
    virtual cv::Size measure_label(const std::string& utf8) const = 0;
    virtual cv::Rect draw_label(
        cv::Mat& frame,
        const std::string& utf8,
        const cv::Point& top_left,
        const cv::Scalar& foreground_bgr,
        const cv::Scalar& background_bgr) = 0;
    virtual ~IUtf8TextRenderer() = default;
};

class WindowsGdiUtf8TextRenderer final : public IUtf8TextRenderer {
public:
    explicit WindowsGdiUtf8TextRenderer(const TextRendererConfig& config);
    ~WindowsGdiUtf8TextRenderer() override;

    WindowsGdiUtf8TextRenderer(const WindowsGdiUtf8TextRenderer&) = delete;
    WindowsGdiUtf8TextRenderer& operator=(const WindowsGdiUtf8TextRenderer&) = delete;

    cv::Size measure_label(const std::string& utf8) const override;
    cv::Rect draw_label(
        cv::Mat& frame,
        const std::string& utf8,
        const cv::Point& top_left,
        const cv::Scalar& foreground_bgr,
        const cv::Scalar& background_bgr) override;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace vehicle_system
