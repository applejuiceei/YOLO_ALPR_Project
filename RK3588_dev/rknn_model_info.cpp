#include <cstring>
#include <iostream>
#include <string>

#include "rknn_api.h"

static const char* tensor_type_name(rknn_tensor_type type) {
    switch (type) {
        case RKNN_TENSOR_FLOAT32: return "float32";
        case RKNN_TENSOR_FLOAT16: return "float16";
        case RKNN_TENSOR_INT8: return "int8";
        case RKNN_TENSOR_UINT8: return "uint8";
        case RKNN_TENSOR_INT16: return "int16";
        case RKNN_TENSOR_UINT16: return "uint16";
        case RKNN_TENSOR_INT32: return "int32";
        case RKNN_TENSOR_UINT32: return "uint32";
        default: return "unknown";
    }
}

static const char* tensor_format_name(rknn_tensor_format fmt) {
    switch (fmt) {
        case RKNN_TENSOR_NCHW: return "NCHW";
        case RKNN_TENSOR_NHWC: return "NHWC";
        case RKNN_TENSOR_NC1HWC2: return "NC1HWC2";
        case RKNN_TENSOR_UNDEFINED: return "UNDEFINED";
        default: return "unknown";
    }
}

static void print_attr(const char* label, const rknn_tensor_attr& attr) {
    std::cout << label << "[" << attr.index << "]"
              << " name=" << attr.name
              << " fmt=" << tensor_format_name(attr.fmt)
              << " type=" << tensor_type_name(attr.type)
              << " qnt_type=" << attr.qnt_type
              << " zp=" << attr.zp
              << " scale=" << attr.scale
              << " dims=[";
    for (uint32_t i = 0; i < attr.n_dims; ++i) {
        if (i) std::cout << ",";
        std::cout << attr.dims[i];
    }
    std::cout << "]"
              << " n_elems=" << attr.n_elems
              << " size=" << attr.size
              << std::endl;
}

static bool inspect_model(const char* path) {
    std::cout << "============================================================" << std::endl;
    std::cout << "MODEL: " << path << std::endl;

    rknn_context ctx = 0;
    int ret = rknn_init(&ctx, (void*)path, 0, 0, nullptr);
    if (ret != RKNN_SUCC) {
        std::cerr << "rknn_init failed, ret=" << ret << std::endl;
        return false;
    }

    rknn_sdk_version version;
    std::memset(&version, 0, sizeof(version));
    ret = rknn_query(ctx, RKNN_QUERY_SDK_VERSION, &version, sizeof(version));
    if (ret == RKNN_SUCC) {
        std::cout << "api_version=" << version.api_version
                  << " drv_version=" << version.drv_version << std::endl;
    }

    rknn_input_output_num io_num;
    std::memset(&io_num, 0, sizeof(io_num));
    ret = rknn_query(ctx, RKNN_QUERY_IN_OUT_NUM, &io_num, sizeof(io_num));
    if (ret != RKNN_SUCC) {
        std::cerr << "RKNN_QUERY_IN_OUT_NUM failed, ret=" << ret << std::endl;
        rknn_destroy(ctx);
        return false;
    }

    std::cout << "inputs=" << io_num.n_input << " outputs=" << io_num.n_output << std::endl;

    for (uint32_t i = 0; i < io_num.n_input; ++i) {
        rknn_tensor_attr attr;
        std::memset(&attr, 0, sizeof(attr));
        attr.index = i;
        ret = rknn_query(ctx, RKNN_QUERY_INPUT_ATTR, &attr, sizeof(attr));
        if (ret == RKNN_SUCC) print_attr("input", attr);
        else std::cerr << "RKNN_QUERY_INPUT_ATTR[" << i << "] failed, ret=" << ret << std::endl;
    }

    for (uint32_t i = 0; i < io_num.n_output; ++i) {
        rknn_tensor_attr attr;
        std::memset(&attr, 0, sizeof(attr));
        attr.index = i;
        ret = rknn_query(ctx, RKNN_QUERY_OUTPUT_ATTR, &attr, sizeof(attr));
        if (ret == RKNN_SUCC) print_attr("output", attr);
        else std::cerr << "RKNN_QUERY_OUTPUT_ATTR[" << i << "] failed, ret=" << ret << std::endl;
    }

    rknn_destroy(ctx);
    return true;
}

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " model1.rknn [model2.rknn ...]" << std::endl;
        return 1;
    }

    bool all_ok = true;
    for (int i = 1; i < argc; ++i) {
        all_ok = inspect_model(argv[i]) && all_ok;
    }
    return all_ok ? 0 : 2;
}
