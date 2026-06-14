cmake_minimum_required(VERSION 3.10)

set(CMAKE_C_COMPILER /home/apple/gcc-arm-10.3-2021.07-x86_64-aarch64-none-linux-gnu/bin/aarch64-none-linux-gnu-gcc)
set(CMAKE_CXX_COMPILER /home/apple/gcc-arm-10.3-2021.07-x86_64-aarch64-none-linux-gnu/bin/aarch64-none-linux-gnu-g++)

project(RK3588_ALPR)
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -Wl,--unresolved-symbols=ignore-in-shared-libs")

set(3RDPARTY_DIR ${CMAKE_SOURCE_DIR}/3rdparty)
set(RKNN_API_DIR /home/apple/rknn-toolkit2/rknpu2/runtime/Linux/librknn_api)

include_directories(
    ${RKNN_API_DIR}/include
    ${3RDPARTY_DIR}/opencv/include
    ${3RDPARTY_DIR}/rga/include
    ${CMAKE_SOURCE_DIR}/src/bytetrack
    ${3RDPARTY_DIR}
    ${3RDPARTY_DIR}/eigen3
)

link_directories(
    ${RKNN_API_DIR}/aarch64
    ${3RDPARTY_DIR}/opencv/lib
    ${3RDPARTY_DIR}/rga/lib
)

add_executable(rknn_model_info rknn_model_info.cpp)
target_link_libraries(rknn_model_info rknnrt)

set(APP_MAIN_SRC ${CMAKE_SOURCE_DIR}/src/main.cpp)
if(EXISTS ${CMAKE_SOURCE_DIR}/main.cpp)
    set(APP_MAIN_SRC ${CMAKE_SOURCE_DIR}/main.cpp)
endif()

set(BYTETRACK_SRCS
    ${CMAKE_SOURCE_DIR}/src/bytetrack/BYTETracker.cpp
    ${CMAKE_SOURCE_DIR}/src/bytetrack/STrack.cpp
    ${CMAKE_SOURCE_DIR}/src/bytetrack/kalmanFilter.cpp
    ${CMAKE_SOURCE_DIR}/src/bytetrack/lapjv.cpp
    ${CMAKE_SOURCE_DIR}/src/bytetrack/utils.cpp
)

if(EXISTS ${APP_MAIN_SRC} AND EXISTS ${CMAKE_SOURCE_DIR}/src/bytetrack/BYTETracker.cpp)
    add_executable(alpr_app
        ${APP_MAIN_SRC}
        ${BYTETRACK_SRCS}
    )

    target_link_libraries(alpr_app
        rknnrt
        opencv_core opencv_imgproc opencv_imgcodecs opencv_videoio
        rga
    )
else()
    message(WARNING "ByteTrack sources not found; only rknn_model_info will be built.")
endif()
