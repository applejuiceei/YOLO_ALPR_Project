cmake_minimum_required(VERSION 3.20)

project(rk3588_vehicle_system VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")

set(PREBUILT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third_party/prebuilt")
set(OpenCV_DIR "${PREBUILT_DIR}/opencv/build")
set(ONNXRUNTIME_ROOT "${PREBUILT_DIR}/onnxruntime-win-x64-1.29.0")

if(NOT EXISTS "${OpenCV_DIR}/OpenCVConfig.cmake")
    message(FATAL_ERROR "OpenCV prebuilt package not found under ${OpenCV_DIR}")
endif()
if(NOT EXISTS "${ONNXRUNTIME_ROOT}/include/onnxruntime_cxx_api.h")
    message(FATAL_ERROR "ONNX Runtime prebuilt package not found under ${ONNXRUNTIME_ROOT}")
endif()

find_package(OpenCV 4.12 REQUIRED)

add_library(vehicle_core
    src/camera/camera_manager.cpp
    src/classifier/pp_vehicle_onnx_color_classifier.cpp
    src/common/config.cpp
    src/common/object_types.cpp
    src/common/utf8_text_renderer.cpp
    src/cropper/vehicle_cropper.cpp
    src/detector/yolo11_onnx_vehicle_detector.cpp
    src/fusion/confidence_weighted_vehicle_fusion.cpp
    src/fusion/confidence_weighted_plate_fusion.cpp
    src/plate/hyperlpr3_onnx_plate_recognizer.cpp
    src/plate/hsv_plate_color_classifier.cpp
    src/plate/opencv_plate_quality_evaluator.cpp
    src/plate/opencv_plate_rectifier.cpp
    src/plate/plate_cropper.cpp
    src/plate/yolo_obb_onnx_plate_detector.cpp
    src/tracker/byte_tracker.cpp
)

target_include_directories(vehicle_core
    PUBLIC
        "${CMAKE_CURRENT_SOURCE_DIR}/include"
    PRIVATE
        "${ONNXRUNTIME_ROOT}/include"
)

target_link_libraries(vehicle_core
    PUBLIC ${OpenCV_LIBS}
    PRIVATE "${ONNXRUNTIME_ROOT}/lib/onnxruntime.lib"
)

if(WIN32)
    target_compile_definitions(vehicle_core PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
    target_compile_options(vehicle_core PRIVATE /W4 /permissive- /utf-8)
    target_link_libraries(vehicle_core PRIVATE Psapi Gdi32)
endif()

add_executable(vehicle_demo src/main.cpp)
target_link_libraries(vehicle_demo PRIVATE vehicle_core)

add_executable(vehicle_detector_test tests/vehicle_detector_test.cpp)
target_link_libraries(vehicle_detector_test PRIVATE vehicle_core)

add_executable(vehicle_cropper_test tests/vehicle_cropper_test.cpp)
target_link_libraries(vehicle_cropper_test PRIVATE vehicle_core)

add_executable(vehicle_cropper_pipeline_test tests/vehicle_cropper_pipeline_test.cpp)
target_link_libraries(vehicle_cropper_pipeline_test PRIVATE vehicle_core)

add_executable(vehicle_color_classifier_test tests/vehicle_color_classifier_test.cpp)
target_link_libraries(vehicle_color_classifier_test PRIVATE vehicle_core)

add_executable(vehicle_tracker_test tests/vehicle_tracker_test.cpp)
target_link_libraries(vehicle_tracker_test PRIVATE vehicle_core)

add_executable(vehicle_fusion_test tests/vehicle_fusion_test.cpp)
target_link_libraries(vehicle_fusion_test PRIVATE vehicle_core)

add_executable(plate_cropper_test tests/plate_cropper_test.cpp)
target_link_libraries(plate_cropper_test PRIVATE vehicle_core)

add_executable(plate_detector_test tests/plate_detector_test.cpp)
target_link_libraries(plate_detector_test PRIVATE vehicle_core)

add_executable(plate_quality_test tests/plate_quality_test.cpp)
target_link_libraries(plate_quality_test PRIVATE vehicle_core)

add_executable(plate_rectifier_test tests/plate_rectifier_test.cpp)
target_link_libraries(plate_rectifier_test PRIVATE vehicle_core)

add_executable(plate_color_classifier_test tests/plate_color_classifier_test.cpp)
target_link_libraries(plate_color_classifier_test PRIVATE vehicle_core)

add_executable(plate_recognizer_test tests/plate_recognizer_test.cpp)
target_link_libraries(plate_recognizer_test PRIVATE vehicle_core)

add_executable(plate_fusion_test tests/plate_fusion_test.cpp)
target_link_libraries(plate_fusion_test PRIVATE vehicle_core)

add_executable(utf8_text_renderer_test tests/utf8_text_renderer_test.cpp)
target_link_libraries(utf8_text_renderer_test PRIVATE vehicle_core)

foreach(target vehicle_demo vehicle_detector_test vehicle_cropper_test vehicle_cropper_pipeline_test vehicle_color_classifier_test vehicle_tracker_test vehicle_fusion_test plate_cropper_test plate_detector_test plate_quality_test plate_rectifier_test plate_color_classifier_test plate_recognizer_test plate_fusion_test utf8_text_renderer_test)
    if(WIN32)
        target_compile_definitions(${target} PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
        target_compile_options(${target} PRIVATE /W4 /permissive- /utf-8)
    endif()
    add_custom_command(TARGET ${target} POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${ONNXRUNTIME_ROOT}/lib/onnxruntime.dll"
            "$<TARGET_FILE_DIR:${target}>"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${PREBUILT_DIR}/opencv/build/x64/vc16/bin/opencv_world4120.dll"
            "$<TARGET_FILE_DIR:${target}>"
    )
endforeach()

enable_testing()
add_test(NAME vehicle_demo_help COMMAND vehicle_demo --help)
add_test(NAME vehicle_cropper_unit COMMAND vehicle_cropper_test)
add_test(NAME vehicle_tracker_unit COMMAND vehicle_tracker_test)
add_test(NAME vehicle_fusion_unit COMMAND vehicle_fusion_test)
add_test(NAME plate_cropper_unit COMMAND plate_cropper_test)
add_test(NAME plate_quality_unit COMMAND plate_quality_test)
add_test(NAME plate_rectifier_unit COMMAND plate_rectifier_test)
add_test(NAME plate_color_classifier_unit COMMAND plate_color_classifier_test)
add_test(NAME plate_recognizer_reference
    COMMAND plate_recognizer_test
        "${CMAKE_CURRENT_SOURCE_DIR}/config/config.yaml"
        "${CMAKE_CURRENT_SOURCE_DIR}/../Dataset/dataset/test/sharp/grab10003.jpg"
        "苏E803JV")
add_test(NAME plate_fusion_unit COMMAND plate_fusion_test)
add_test(NAME utf8_text_renderer_unit COMMAND utf8_text_renderer_test)
