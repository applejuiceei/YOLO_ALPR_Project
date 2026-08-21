#include "common/utf8_text_renderer.hpp"

#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

void require(bool condition, const std::string& message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

}  // namespace

int main() {
    try {
        const std::vector<std::uint16_t> beijing = vehicle_system::utf8_to_utf16("京A12345");
        const std::vector<std::uint16_t> henan = vehicle_system::utf8_to_utf16("豫JC521G");
        require(beijing.size() == 7 && beijing[0] == 0x4EACU && beijing[1] == 'A',
            "京A12345 UTF-16 conversion is incorrect");
        require(henan.size() == 7 && henan[0] == 0x8C6BU && henan[1] == 'J',
            "豫JC521G UTF-16 conversion is incorrect");
        bool invalid_rejected = false;
        try {
            vehicle_system::utf8_to_utf16(std::string("\xE4\x41", 2));
        } catch (const std::invalid_argument&) {
            invalid_rejected = true;
        }
        require(invalid_rejected, "invalid UTF-8 must be rejected");

        vehicle_system::TextRendererConfig config;
        vehicle_system::WindowsGdiUtf8TextRenderer renderer(config);
        cv::Mat image(120, 600, CV_8UC3, cv::Scalar(30, 30, 30));
        const cv::Rect first = renderer.draw_label(image, "车牌: 京A12345 0.95",
            cv::Point(10, 10), cv::Scalar(20, 20, 20), cv::Scalar(0, 230, 255));
        const cv::Rect second = renderer.draw_label(image, "车牌(单帧): 豫JC521G 0.86",
            cv::Point(10, 60), cv::Scalar(245, 245, 245), cv::Scalar(80, 50, 20));
        require(!first.empty() && !second.empty(), "rendered label rectangles are empty");
        require(cv::countNonZero(image.reshape(1) != 30) > 100,
            "Unicode labels did not change the image");
        std::cout << "UTF-8 text renderer test passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "UTF-8 text renderer test failed: " << error.what() << '\n';
        return 1;
    }
}
