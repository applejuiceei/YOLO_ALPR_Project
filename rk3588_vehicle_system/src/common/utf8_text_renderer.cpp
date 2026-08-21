#include "common/utf8_text_renderer.hpp"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <opencv2/imgproc.hpp>
#include <stdexcept>
#include <string>
#include <utility>

#ifdef _WIN32
#include <windows.h>
#endif

namespace vehicle_system {

std::vector<std::uint16_t> utf8_to_utf16(const std::string& utf8) {
    std::vector<std::uint16_t> utf16;
    utf16.reserve(utf8.size());
    for (std::size_t index = 0; index < utf8.size();) {
        const std::uint8_t first = static_cast<std::uint8_t>(utf8[index]);
        std::uint32_t codepoint = 0;
        std::size_t length = 0;
        std::uint32_t minimum = 0;
        if (first <= 0x7FU) {
            codepoint = first;
            length = 1;
        } else if ((first & 0xE0U) == 0xC0U) {
            codepoint = first & 0x1FU;
            length = 2;
            minimum = 0x80U;
        } else if ((first & 0xF0U) == 0xE0U) {
            codepoint = first & 0x0FU;
            length = 3;
            minimum = 0x800U;
        } else if ((first & 0xF8U) == 0xF0U) {
            codepoint = first & 0x07U;
            length = 4;
            minimum = 0x10000U;
        } else {
            throw std::invalid_argument("Invalid UTF-8 leading byte");
        }
        if (index + length > utf8.size()) {
            throw std::invalid_argument("Truncated UTF-8 sequence");
        }
        for (std::size_t offset = 1; offset < length; ++offset) {
            const std::uint8_t continuation =
                static_cast<std::uint8_t>(utf8[index + offset]);
            if ((continuation & 0xC0U) != 0x80U) {
                throw std::invalid_argument("Invalid UTF-8 continuation byte");
            }
            codepoint = (codepoint << 6U) | (continuation & 0x3FU);
        }
        if ((length > 1 && codepoint < minimum) || codepoint > 0x10FFFFU ||
            (codepoint >= 0xD800U && codepoint <= 0xDFFFU)) {
            throw std::invalid_argument("Invalid UTF-8 code point");
        }
        if (codepoint <= 0xFFFFU) {
            utf16.push_back(static_cast<std::uint16_t>(codepoint));
        } else {
            codepoint -= 0x10000U;
            utf16.push_back(static_cast<std::uint16_t>(0xD800U + (codepoint >> 10U)));
            utf16.push_back(static_cast<std::uint16_t>(0xDC00U + (codepoint & 0x3FFU)));
        }
        index += length;
    }
    return utf16;
}

void configure_utf8_console() {
#ifdef _WIN32
    SetConsoleOutputCP(CP_UTF8);
    SetConsoleCP(CP_UTF8);
#endif
}

struct WindowsGdiUtf8TextRenderer::Impl {
    explicit Impl(const TextRendererConfig& renderer_config) : config(renderer_config) {
        if (config.backend != "windows_gdi") {
            throw std::invalid_argument("Text renderer backend must be windows_gdi on Windows PC");
        }
        if (config.font_family.empty() || config.font_height <= 0 ||
            config.horizontal_padding < 0 || config.vertical_padding < 0) {
            throw std::invalid_argument("Text renderer configuration is invalid");
        }
#ifdef _WIN32
        const std::vector<std::uint16_t> family_utf16 = utf8_to_utf16(config.font_family);
        std::wstring family;
        family.reserve(family_utf16.size());
        for (const std::uint16_t code_unit : family_utf16) {
            family.push_back(static_cast<wchar_t>(code_unit));
        }
        dc = CreateCompatibleDC(nullptr);
        if (dc == nullptr) {
            throw std::runtime_error("CreateCompatibleDC failed for text renderer");
        }
        font = CreateFontW(-config.font_height, 0, 0, 0, FW_SEMIBOLD, FALSE, FALSE, FALSE,
            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, ANTIALIASED_QUALITY,
            DEFAULT_PITCH | FF_DONTCARE, family.c_str());
        if (font == nullptr) {
            DeleteDC(dc);
            dc = nullptr;
            throw std::runtime_error("CreateFontW failed for text renderer");
        }
        old_font = SelectObject(dc, font);
        SetBkMode(dc, TRANSPARENT);
        TEXTMETRICW metrics{};
        if (!GetTextMetricsW(dc, &metrics)) {
            SelectObject(dc, old_font);
            old_font = nullptr;
            DeleteObject(font);
            font = nullptr;
            DeleteDC(dc);
            dc = nullptr;
            throw std::runtime_error("GetTextMetricsW failed for text renderer");
        }
        text_height = metrics.tmHeight;
#else
        throw std::runtime_error(
            "WindowsGdiUtf8TextRenderer is unavailable on this platform; use a FreeType backend");
#endif
    }

    ~Impl() {
#ifdef _WIN32
        if (dc != nullptr && old_font != nullptr) {
            SelectObject(dc, old_font);
        }
        if (font != nullptr) {
            DeleteObject(font);
        }
        if (dc != nullptr) {
            DeleteDC(dc);
        }
#endif
    }

#ifdef _WIN32
    std::wstring wide(const std::string& utf8) const {
        const std::vector<std::uint16_t> utf16 = utf8_to_utf16(utf8);
        std::wstring value;
        value.reserve(utf16.size());
        for (const std::uint16_t code_unit : utf16) {
            value.push_back(static_cast<wchar_t>(code_unit));
        }
        return value;
    }

    cv::Size measure(const std::string& utf8) const {
        const std::wstring value = wide(utf8);
        SIZE extent{};
        if (!GetTextExtentPoint32W(dc, value.c_str(), static_cast<int>(value.size()), &extent)) {
            throw std::runtime_error("GetTextExtentPoint32W failed for text renderer");
        }
        return {extent.cx + config.horizontal_padding * 2,
            std::max(text_height, static_cast<int>(extent.cy)) + config.vertical_padding * 2};
    }
#endif

    TextRendererConfig config;
    int text_height = 0;
#ifdef _WIN32
    HDC dc = nullptr;
    HFONT font = nullptr;
    HGDIOBJ old_font = nullptr;
#endif
};

WindowsGdiUtf8TextRenderer::WindowsGdiUtf8TextRenderer(const TextRendererConfig& config)
    : impl_(std::make_unique<Impl>(config)) {}

WindowsGdiUtf8TextRenderer::~WindowsGdiUtf8TextRenderer() = default;

cv::Size WindowsGdiUtf8TextRenderer::measure_label(const std::string& utf8) const {
#ifdef _WIN32
    return impl_->measure(utf8);
#else
    (void)utf8;
    throw std::runtime_error("Windows GDI text renderer is unavailable");
#endif
}

cv::Rect WindowsGdiUtf8TextRenderer::draw_label(
    cv::Mat& frame,
    const std::string& utf8,
    const cv::Point& top_left,
    const cv::Scalar& foreground_bgr,
    const cv::Scalar& background_bgr) {
    if (frame.empty() || frame.type() != CV_8UC3) {
        throw std::invalid_argument("Text renderer expects a non-empty CV_8UC3 frame");
    }
#ifdef _WIN32
    const std::wstring value = impl_->wide(utf8);
    const cv::Size label_size = impl_->measure(utf8);
    if (label_size.width <= 0 || label_size.height <= 0) {
        return {};
    }

    BITMAPINFO bitmap_info{};
    bitmap_info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bitmap_info.bmiHeader.biWidth = label_size.width;
    bitmap_info.bmiHeader.biHeight = -label_size.height;
    bitmap_info.bmiHeader.biPlanes = 1;
    bitmap_info.bmiHeader.biBitCount = 32;
    bitmap_info.bmiHeader.biCompression = BI_RGB;
    void* pixels = nullptr;
    HBITMAP bitmap = CreateDIBSection(
        impl_->dc, &bitmap_info, DIB_RGB_COLORS, &pixels, nullptr, 0);
    if (bitmap == nullptr || pixels == nullptr) {
        throw std::runtime_error("CreateDIBSection failed for text label");
    }
    HGDIOBJ old_bitmap = SelectObject(impl_->dc, bitmap);
    cv::Mat bgra(label_size, CV_8UC4, pixels);
    bgra.setTo(cv::Scalar(background_bgr[0], background_bgr[1], background_bgr[2], 255));
    SetTextColor(impl_->dc, RGB(
        static_cast<BYTE>(std::clamp(foreground_bgr[2], 0.0, 255.0)),
        static_cast<BYTE>(std::clamp(foreground_bgr[1], 0.0, 255.0)),
        static_cast<BYTE>(std::clamp(foreground_bgr[0], 0.0, 255.0))));
    const BOOL drawn = TextOutW(impl_->dc, impl_->config.horizontal_padding,
        impl_->config.vertical_padding, value.c_str(), static_cast<int>(value.size()));
    cv::Mat bgr;
    if (drawn) {
        cv::cvtColor(bgra, bgr, cv::COLOR_BGRA2BGR);
    }
    SelectObject(impl_->dc, old_bitmap);
    DeleteObject(bitmap);
    if (!drawn) {
        throw std::runtime_error("TextOutW failed for UTF-8 label");
    }

    const cv::Rect intended(top_left, label_size);
    const cv::Rect clipped = intended & cv::Rect(0, 0, frame.cols, frame.rows);
    if (!clipped.empty()) {
        const cv::Rect patch_region(
            clipped.x - intended.x, clipped.y - intended.y, clipped.width, clipped.height);
        bgr(patch_region).copyTo(frame(clipped));
    }
    return clipped;
#else
    (void)utf8;
    (void)top_left;
    (void)foreground_bgr;
    (void)background_bgr;
    throw std::runtime_error("Windows GDI text renderer is unavailable");
#endif
}

}  // namespace vehicle_system
