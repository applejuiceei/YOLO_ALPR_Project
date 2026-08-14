#include <iostream>
#include <vector>
#include <numeric>
#include <algorithm>
#include <string>
#include <chrono>
#include <cstdlib>
#include <unordered_map>
#include <deque>
#include <fstream>
#include <cctype>

#include "rknn_api.h"
#include <opencv2/opencv.hpp>
#include "BYTETracker.h"

// ============================================================================
// 🛡️ 0. 车牌字符串杂质清洗器 (拦截模型幻觉)
// ============================================================================
std::string clean_plate_string(std::string raw_str) {
    std::string clean_str = raw_str;
    std::string chars_to_remove = "-_.;:'\" ";
    for (char c : chars_to_remove) {
        clean_str.erase(std::remove(clean_str.begin(), clean_str.end(), c), clean_str.end());
    }
    return clean_str;
}

// ============================================================================
// 📚 1. 字典读取与 OCR CTC 解码引擎
// ============================================================================
std::vector<std::string> load_dict(const std::string& path) {
    std::vector<std::string> dict;
    std::ifstream file(path);
    std::string line;
    dict.push_back("blank"); // 默认索引0为 CTC blank
    while (std::getline(file, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        dict.push_back(line);
    }
    dict.push_back(" "); // 加上空格字符
    return dict;
}

std::string ctc_decode(const float* preds, int seq_len, int num_classes, const std::vector<std::string>& dict) {
    std::string result = "";
    int pre_idx = 0;
    for (int i = 0; i < seq_len; ++i) {
        int max_idx = 0;
        float max_val = preds[i * num_classes];
        for (int j = 1; j < num_classes; ++j) {
            if (preds[i * num_classes + j] > max_val) {
                max_val = preds[i * num_classes + j];
                max_idx = j;
            }
        }
        if (max_idx != 0 && max_idx != pre_idx) {
            if (max_idx < dict.size()) {
                result += dict[max_idx];
            }
        }
        pre_idx = max_idx;
    }
    return result;
}

// ============================================================================
// 🎯 2. 一阶段：手写极简 NMS 引擎
// ============================================================================
float calculateIoU(const cv::Rect& a, const cv::Rect& b) {
    int inter_area = (a & b).area();
    if (inter_area == 0) return 0.0f;
    int union_area = a.area() + b.area() - inter_area;
    return (float)inter_area / union_area;
}

void custom_NMS(const std::vector<cv::Rect>& boxes, const std::vector<float>& confidences, const std::vector<int>& class_ids,
                float conf_threshold, float nms_threshold, std::vector<int>& indices) {
    indices.clear();
    if (boxes.empty()) return;
    std::vector<int> order(confidences.size());
    std::iota(order.begin(), order.end(), 0);
    std::sort(order.begin(), order.end(), [&confidences](int i1, int i2) { return confidences[i1] > confidences[i2]; });
    std::vector<bool> keep(confidences.size(), true);
    for (size_t i = 0; i < order.size(); ++i) {
        int idx = order[i];
        if (!keep[idx] || confidences[idx] < conf_threshold) continue;
        indices.push_back(idx);
        for (size_t j = i + 1; j < order.size(); ++j) {
            int next_idx = order[j];
            if (!keep[next_idx]) continue;
            if (class_ids[idx] == class_ids[next_idx]) {
                if (calculateIoU(boxes[idx], boxes[next_idx]) > nms_threshold) keep[next_idx] = false;
            }
        }
    }
}

// ============================================================================
// 🌀 3. 二阶段与状态机：OBB 解析、透视拉平、滑动投票、抓拍兜底
// ============================================================================
struct OBBBox { float cx, cy, w, h, score, angle_rad; };

void getInputSize(const rknn_tensor_attr& attr, int& width, int& height) {
    if (attr.fmt == RKNN_TENSOR_NCHW) {
        height = attr.dims[2];
        width = attr.dims[3];
    } else {
        height = attr.dims[1];
        width = attr.dims[2];
    }
}

void orderPoints(const std::vector<cv::Point2f>& in_pts, std::vector<cv::Point2f>& out_pts) {
    out_pts.resize(4);
    std::vector<cv::Point2f> sorted_by_x = in_pts;
    std::sort(sorted_by_x.begin(), sorted_by_x.end(), [](const cv::Point2f& a, const cv::Point2f& b) { return a.x < b.x; });
    cv::Point2f left_1 = sorted_by_x[0], left_2 = sorted_by_x[1];
    cv::Point2f right_1 = sorted_by_x[2], right_2 = sorted_by_x[3];

    if (left_1.y < left_2.y) { out_pts[0] = left_1; out_pts[3] = left_2; }
    else                     { out_pts[0] = left_2; out_pts[3] = left_1; }
    if (right_1.y < right_2.y) { out_pts[1] = right_1; out_pts[2] = right_2; }
    else                       { out_pts[1] = right_2; out_pts[2] = right_1; }
}

std::vector<cv::Point2f> expand_rect(const std::vector<cv::Point2f>& rect, float pad_x = 5.0f, float pad_y = 5.0f) {
    std::vector<cv::Point2f> new_rect = rect;
    new_rect[0] = cv::Point2f(rect[0].x - pad_x, rect[0].y - pad_y);
    new_rect[1] = cv::Point2f(rect[1].x + pad_x, rect[1].y - pad_y);
    new_rect[2] = cv::Point2f(rect[2].x + pad_x, rect[2].y + pad_y);
    new_rect[3] = cv::Point2f(rect[3].x - pad_x, rect[3].y + pad_y);
    return new_rect;
}

bool processPlateOBB(const cv::Mat& src_roi, const float* net_output_ptr, int plate_model_width, int plate_model_height,
                     int plate_num_anchors, int plate_num_channels, bool plate_is_transposed,
                     float conf_threshold, cv::Mat& warped_plate, std::vector<cv::Point2f>& pts_local) {
    bool found = false;
    OBBBox best_plate; best_plate.score = -1.0f;

    auto obb_value = [&](int anchor, int channel) -> float {
        if (plate_is_transposed) {
            return net_output_ptr[anchor * plate_num_channels + channel];
        }
        return net_output_ptr[channel * plate_num_anchors + anchor];
    };

    for (int i = 0; i < plate_num_anchors; ++i) {
        float score = obb_value(i, 4);
        if (score > conf_threshold && score > best_plate.score) {
            best_plate.cx = obb_value(i, 0); best_plate.cy = obb_value(i, 1);
            best_plate.w = obb_value(i, 2);  best_plate.h = obb_value(i, 3);
            best_plate.score = score;        best_plate.angle_rad = obb_value(i, 5);
            found = true;
        }
    }
    if (!found) return false;

    // 缩放还原 (修复绿框乱跑的核心逻辑)
    float scale_x = (float)src_roi.cols / (float)plate_model_width;
    float scale_y = (float)src_roi.rows / (float)plate_model_height;
    
    best_plate.cx *= scale_x; best_plate.w *= scale_x;
    best_plate.cy *= scale_y; best_plate.h *= scale_y;

    float cos_a = cos(best_plate.angle_rad), sin_a = sin(best_plate.angle_rad);
    float hw = best_plate.w / 2.0f, hh = best_plate.h / 2.0f;

    std::vector<cv::Point2f> raw_vertices(4);
    raw_vertices[0] = cv::Point2f(best_plate.cx - hw * cos_a + hh * sin_a, best_plate.cy - hw * sin_a - hh * cos_a);
    raw_vertices[1] = cv::Point2f(best_plate.cx + hw * cos_a + hh * sin_a, best_plate.cy + hw * sin_a - hh * cos_a);
    raw_vertices[2] = cv::Point2f(best_plate.cx + hw * cos_a - hh * sin_a, best_plate.cy + hw * sin_a + hh * cos_a);
    raw_vertices[3] = cv::Point2f(best_plate.cx - hw * cos_a - hh * sin_a, best_plate.cy - hw * sin_a + hh * cos_a);
    pts_local = raw_vertices;

    std::vector<cv::Point2f> ordered_vertices;
    orderPoints(raw_vertices, ordered_vertices);
    cv::Point2f dst_vertices[4] = { {0,0}, {320,0}, {320,96}, {0,96} };
    cv::Mat M = cv::getPerspectiveTransform(ordered_vertices.data(), dst_vertices);
    cv::warpPerspective(src_roi, warped_plate, M, cv::Size(320, 96)); // 拉平为 320x96
    return true;
}

class ALPRVoter {
private:
    int max_history, consensus_threshold;
    std::unordered_map<int, std::deque<std::string>> history;
public:
    ALPRVoter(int max_hist = 10, int threshold = 2) : max_history(max_hist), consensus_threshold(threshold) {}
    void add_record(int track_id) { if (history.find(track_id) == history.end()) history[track_id] = std::deque<std::string>(); }
    bool vote(int track_id, const std::string& text, std::string& best_text_out) {
        if (text.empty()) return false;
        add_record(track_id);
        history[track_id].push_back(text);
        if (history[track_id].size() > max_history) history[track_id].pop_front();

        std::unordered_map<std::string, int> counts;
        int max_count = 0; std::string best_text = "";
        for (const auto& t : history[track_id]) {
            counts[t]++;
            if (counts[t] > max_count) { max_count = counts[t]; best_text = t; }
        }
        if (max_count >= consensus_threshold) { best_text_out = best_text; return true; }
        return false;
    }
    void get_best_guess(int track_id, std::string& best_text_out, int& vote_count) {
        best_text_out = ""; vote_count = 0;
        if (history.find(track_id) == history.end() || history[track_id].empty()) return;
        std::unordered_map<std::string, int> counts;
        for (const auto& t : history[track_id]) {
            counts[t]++;
            if (counts[t] > vote_count) { vote_count = counts[t]; best_text_out = t; }
        }
    }
    void remove_record(int track_id) { history.erase(track_id); }
};

struct VehicleState {
    bool has_final_result = false;
    std::string final_text = "";
    bool was_snapshot = false;
    cv::Mat last_frame;
    cv::Rect last_box;
    std::vector<cv::Point2f> last_exp_rect;
    cv::Mat last_flattened_plate;
};

// ============================================================================
// 🚀 主程序开始 (终极三擎全开工业流水线 + 智能摄像头挂载)
// ============================================================================
int main(int argc, char** argv) {
    if (argc < 6) {
        std::cerr << "❌ 用法: ./alpr_app <寻车.rknn> <找牌OBB.rknn> <OCR识别.rknn> <字典.txt> <视频路径或摄像头ID(如0)>" << std::endl;
        return -1;
    }

    const char* vehicle_model_path = argv[1];
    const char* plate_model_path   = argv[2];
    const char* rec_model_path     = argv[3];
    const char* dict_path          = argv[4];
    std::string input_source       = argv[5];

    std::cout << "--> 📚 正在加载 OCR 字典..." << std::endl;
    std::vector<std::string> ocr_dict = load_dict(dict_path);

    std::cout << "--> 🧹 正在清理抓拍缓存..." << std::endl;
    system("rm -rf captures && mkdir -p captures");
    std::string snapshot_dir = "./captures";

    // --- 1. 初始化 一阶段 RKNN 引擎 (寻车) ---
    rknn_context ctx_vehicle;
    rknn_init(&ctx_vehicle, (void*)vehicle_model_path, 0, 0, NULL);
    rknn_input_output_num io_num_vehicle;
    rknn_query(ctx_vehicle, RKNN_QUERY_IN_OUT_NUM, &io_num_vehicle, sizeof(io_num_vehicle));
    rknn_tensor_attr input_attrs[io_num_vehicle.n_input];
    memset(input_attrs, 0, sizeof(input_attrs)); input_attrs[0].index = 0;
    rknn_query(ctx_vehicle, RKNN_QUERY_INPUT_ATTR, &(input_attrs[0]), sizeof(rknn_tensor_attr));
    int model_width = 0, model_height = 0;
    getInputSize(input_attrs[0], model_width, model_height);
    rknn_tensor_attr output_attrs[io_num_vehicle.n_output];
    memset(output_attrs, 0, sizeof(output_attrs)); output_attrs[0].index = 0;
    rknn_query(ctx_vehicle, RKNN_QUERY_OUTPUT_ATTR, &(output_attrs[0]), sizeof(rknn_tensor_attr));
    
    int num_channels = 0, num_anchors = 0;
    if (output_attrs[0].dims[1] > output_attrs[0].dims[2]) { num_anchors = output_attrs[0].dims[1]; num_channels = output_attrs[0].dims[2]; }
    else { num_channels = output_attrs[0].dims[1]; num_anchors = output_attrs[0].dims[2]; }
    int num_classes = num_channels - 4;
    bool is_transposed = (output_attrs[0].dims[1] == num_anchors);

    // --- 2. 初始化 二阶段 RKNN 引擎 (找牌 OBB) ---
    rknn_context ctx_plate;
    rknn_init(&ctx_plate, (void*)plate_model_path, 0, 0, NULL);
    rknn_input_output_num io_num_plate;
    rknn_query(ctx_plate, RKNN_QUERY_IN_OUT_NUM, &io_num_plate, sizeof(io_num_plate));
    rknn_tensor_attr plate_input_attr[io_num_plate.n_input];
    memset(plate_input_attr, 0, sizeof(plate_input_attr)); plate_input_attr[0].index = 0;
    rknn_query(ctx_plate, RKNN_QUERY_INPUT_ATTR, &(plate_input_attr[0]), sizeof(rknn_tensor_attr));
    int plate_model_width = 0, plate_model_height = 0;
    getInputSize(plate_input_attr[0], plate_model_width, plate_model_height);

    rknn_tensor_attr plate_output_attr[io_num_plate.n_output];
    memset(plate_output_attr, 0, sizeof(plate_output_attr)); plate_output_attr[0].index = 0;
    rknn_query(ctx_plate, RKNN_QUERY_OUTPUT_ATTR, &(plate_output_attr[0]), sizeof(rknn_tensor_attr));
    int plate_num_channels = 0, plate_num_anchors = 0;
    if (plate_output_attr[0].dims[1] > plate_output_attr[0].dims[2]) {
        plate_num_anchors = plate_output_attr[0].dims[1];
        plate_num_channels = plate_output_attr[0].dims[2];
    } else {
        plate_num_channels = plate_output_attr[0].dims[1];
        plate_num_anchors = plate_output_attr[0].dims[2];
    }
    bool plate_is_transposed = (plate_output_attr[0].dims[1] == plate_num_anchors);
    std::cout << "--> OBB input: " << plate_model_width << "x" << plate_model_height
              << ", output channels=" << plate_num_channels
              << ", anchors=" << plate_num_anchors << std::endl;

    // --- 3. 初始化 三阶段 RKNN 引擎 (OCR 识字) ---
    rknn_context ctx_rec;
    rknn_init(&ctx_rec, (void*)rec_model_path, 0, 0, NULL);
    rknn_input_output_num io_num_rec;
    rknn_query(ctx_rec, RKNN_QUERY_IN_OUT_NUM, &io_num_rec, sizeof(io_num_rec));
    rknn_tensor_attr rec_out_attr[io_num_rec.n_output];
    memset(rec_out_attr, 0, sizeof(rec_out_attr)); rec_out_attr[0].index = 0;
    rknn_query(ctx_rec, RKNN_QUERY_OUTPUT_ATTR, &(rec_out_attr[0]), sizeof(rknn_tensor_attr));
    int rec_seq_len = rec_out_attr[0].dims[1];
    int rec_num_classes = rec_out_attr[0].dims[2];

    BYTETracker tracker(30, 30);
    ALPRVoter voter(10, 2);
    std::unordered_map<int, VehicleState> vehicle_states;
    const int ROI_MARGIN = 50;

    // ==========================================
    // 🎥 智能双轨视频源引擎
    // ==========================================
    cv::VideoCapture cap;
    bool is_camera = !input_source.empty();
    for (char c : input_source) { if (!std::isdigit(c)) { is_camera = false; break; } }

    if (is_camera) {
        int cam_id = std::stoi(input_source);
        std::cout << "--> 📷 正在挂载物理 USB 摄像头 ID: " << cam_id << std::endl;
        cap.open(cam_id, cv::CAP_V4L2);
        cap.set(cv::CAP_PROP_FRAME_WIDTH, 1280);
        cap.set(cv::CAP_PROP_FRAME_HEIGHT, 720);
        cap.set(cv::CAP_PROP_FPS, 30);
    } else if (input_source == "mipi") {
        std::cout << "--> 📷 正在挂载 MIPI CSI 硬件流..." << std::endl;
        std::string pipeline = "v4l2src device=/dev/video22 ! videoconvert ! appsink";
        cap.open(pipeline, cv::CAP_GSTREAMER);
        if (!cap.isOpened()) {
            cap.open("/dev/video22", cv::CAP_V4L2);
        }
    } else {
        std::cout << "--> 🎬 正在加载测试视频流: " << input_source << std::endl;
        cap.open(input_source);
    }

    if (!cap.isOpened()) {
        std::cerr << "❌ 致命错误：无法打开视频流或摄像头！" << std::endl;
        return -1;
    }

    cv::Mat orig_img;
    int frame_count = 0;
    std::cout << "--> 🚀 终极三擎启动，开始执行识别抓拍！" << std::endl;

    while (cap.read(orig_img)) {
        frame_count++;
        auto start = std::chrono::high_resolution_clock::now();
        cv::Mat raw_full_frame = orig_img.clone();
        std::vector<int> current_frame_track_ids;

        // [一阶段] 寻车预处理与推理
        cv::Mat resized_img;
        cv::resize(orig_img, resized_img, cv::Size(model_width, model_height));
        cv::cvtColor(resized_img, resized_img, cv::COLOR_BGR2RGB);

        rknn_input inputs[1]; memset(inputs, 0, sizeof(inputs));
        inputs[0].index = 0; inputs[0].type = RKNN_TENSOR_UINT8;
        inputs[0].size = resized_img.cols * resized_img.rows * resized_img.channels();
        inputs[0].fmt = RKNN_TENSOR_NHWC; inputs[0].buf = resized_img.data;
        rknn_inputs_set(ctx_vehicle, io_num_vehicle.n_input, inputs);
        rknn_run(ctx_vehicle, NULL);

        rknn_output outputs[1]; memset(outputs, 0, sizeof(outputs));
        outputs[0].want_float = 1;
        rknn_outputs_get(ctx_vehicle, io_num_vehicle.n_output, outputs, NULL);

        float* out_data = (float*)outputs[0].buf;
        float rx = (float)orig_img.cols / model_width;
        float ry = (float)orig_img.rows / model_height;
        std::vector<cv::Rect> boxes; std::vector<float> confidences; std::vector<int> class_ids;

        for (int i = 0; i < num_anchors; ++i) {
            float max_conf = 0.0f; int best_class = -1;
            for (int c = 0; c < num_classes; ++c) {
                float conf = is_transposed ? out_data[i * num_channels + 4 + c] : out_data[(4 + c) * num_anchors + i];
                if (conf > max_conf) { max_conf = conf; best_class = c; }
            }
            if (max_conf > 0.65f && (best_class == 2 || best_class == 3 || best_class == 5 || best_class == 7)) {
                float cx = is_transposed ? out_data[i * num_channels + 0] : out_data[0 * num_anchors + i];
                float cy = is_transposed ? out_data[i * num_channels + 1] : out_data[1 * num_anchors + i];
                float w  = is_transposed ? out_data[i * num_channels + 2] : out_data[2 * num_anchors + i];
                float h  = is_transposed ? out_data[i * num_channels + 3] : out_data[3 * num_anchors + i];
                boxes.push_back(cv::Rect((int)((cx - w / 2.0f) * rx), (int)((cy - h / 2.0f) * ry), (int)(w * rx), (int)(h * ry)));
                confidences.push_back(max_conf); class_ids.push_back(best_class);
            }
        }

        std::vector<int> indices;
        custom_NMS(boxes, confidences, class_ids, 0.65f, 0.45f, indices);
        std::vector<Object> detect_objs;
        for (int idx : indices) {
            cv::Rect box = boxes[idx];
            if (box.width > 50 && box.height > 50) {
                Object obj; obj.rect = box; obj.label = class_ids[idx]; obj.prob = confidences[idx];
                detect_objs.push_back(obj);
            }
        }

        std::vector<STrack> output_stracks = tracker.update(detect_objs);

        // [二阶段 + 三阶段] OBB 找牌 -> OCR 识字
        for (const auto& strack : output_stracks) {
            int track_id = strack.track_id;
            current_frame_track_ids.push_back(track_id);
            std::vector<float> tlwh = strack.tlwh;

            int vx1 = std::max(0, (int)tlwh[0]), vy1 = std::max(0, (int)tlwh[1]);
            int vx2 = std::min(orig_img.cols, (int)(tlwh[0] + tlwh[2])), vy2 = std::min(orig_img.rows, (int)(tlwh[1] + tlwh[3]));
            cv::Rect vehicle_rect(vx1, vy1, vx2 - vx1, vy2 - vy1);

            if (vehicle_rect.area() <= 0) continue;

            if (vehicle_states.find(track_id) == vehicle_states.end()) {
                vehicle_states[track_id] = VehicleState(); voter.add_record(track_id);
            }
            VehicleState& state = vehicle_states[track_id];

            if (state.has_final_result) {
                cv::rectangle(orig_img, vehicle_rect, cv::Scalar(0, 255, 0), 2);
                cv::putText(orig_img, "ID:" + std::to_string(track_id) + " " + state.final_text,
                            cv::Point(vx1, vy1 - 10), cv::FONT_HERSHEY_SIMPLEX, 1.0, cv::Scalar(0, 255, 0), 2);
                continue;
            }

            int cx1 = std::max(0, vx1 - ROI_MARGIN), cy1 = std::max(0, vy1 - ROI_MARGIN);
            int cx2 = std::min(orig_img.cols, vx2 + ROI_MARGIN), cy2 = std::min(orig_img.rows, vy2 + ROI_MARGIN);
            cv::Mat roi_crop = raw_full_frame(cv::Rect(cx1, cy1, cx2 - cx1, cy2 - cy1)).clone();

            cv::Mat plate_resized;
            cv::resize(roi_crop, plate_resized, cv::Size(plate_model_width, plate_model_height));
            cv::cvtColor(plate_resized, plate_resized, cv::COLOR_BGR2RGB);

            rknn_input inputs_plate[1]; memset(inputs_plate, 0, sizeof(inputs_plate));
            inputs_plate[0].index = 0; inputs_plate[0].type = RKNN_TENSOR_UINT8;
            inputs_plate[0].size = plate_resized.cols * plate_resized.rows * plate_resized.channels();
            inputs_plate[0].fmt = RKNN_TENSOR_NHWC; inputs_plate[0].buf = plate_resized.data;
            rknn_inputs_set(ctx_plate, io_num_plate.n_input, inputs_plate);
            rknn_run(ctx_plate, NULL);

            rknn_output outputs_plate[1]; memset(outputs_plate, 0, sizeof(outputs_plate));
            outputs_plate[0].want_float = 1;
            rknn_outputs_get(ctx_plate, io_num_plate.n_output, outputs_plate, NULL);

            float* obb_out_ptr = (float*)outputs_plate[0].buf;
            cv::Mat flattened_plate;
            std::vector<cv::Point2f> pts_local;

            bool found_plate = processPlateOBB(roi_crop, obb_out_ptr, plate_model_width, plate_model_height,
                                               plate_num_anchors, plate_num_channels, plate_is_transposed,
                                               0.5f, flattened_plate, pts_local);
            rknn_outputs_release(ctx_plate, io_num_plate.n_output, outputs_plate);

            if (found_plate && !flattened_plate.empty()) {
                std::vector<cv::Point2f> pts_global(4);
                for (int i = 0; i < 4; i++) pts_global[i] = cv::Point2f(pts_local[i].x + cx1, pts_local[i].y + cy1);
                std::vector<cv::Point2f> exp_rect = expand_rect(pts_global, 5.0f, 5.0f);

                state.last_frame = raw_full_frame.clone();
                state.last_box = vehicle_rect;
                state.last_exp_rect = exp_rect;
                state.last_flattened_plate = flattened_plate.clone();

                // ⭐ OCR NPU 推理 ⭐
                cv::Mat rec_input;
                cv::resize(flattened_plate, rec_input, cv::Size(320, 48));
                cv::cvtColor(rec_input, rec_input, cv::COLOR_BGR2RGB);

                rknn_input inputs_rec[1]; memset(inputs_rec, 0, sizeof(inputs_rec));
                inputs_rec[0].index = 0; inputs_rec[0].type = RKNN_TENSOR_UINT8;
                inputs_rec[0].size = rec_input.cols * rec_input.rows * rec_input.channels();
                inputs_rec[0].fmt = RKNN_TENSOR_NHWC; inputs_rec[0].buf = rec_input.data;
                rknn_inputs_set(ctx_rec, io_num_rec.n_input, inputs_rec);
                rknn_run(ctx_rec, NULL);

                rknn_output outputs_rec[1]; memset(outputs_rec, 0, sizeof(outputs_rec));
                outputs_rec[0].want_float = 1;
                rknn_outputs_get(ctx_rec, io_num_rec.n_output, outputs_rec, NULL);

                float* rec_out_ptr = (float*)outputs_rec[0].buf;
                std::string raw_ocr_text = ctc_decode(rec_out_ptr, rec_seq_len, rec_num_classes, ocr_dict);
                rknn_outputs_release(ctx_rec, io_num_rec.n_output, outputs_rec);

                std::string final_result;
                raw_ocr_text = clean_plate_string(raw_ocr_text);
                bool is_stable = voter.vote(track_id, raw_ocr_text, final_result);

                if (is_stable && final_result.length() >= 7) {
                    state.has_final_result = true;
                    state.final_text = final_result;
                    std::cout << "✅ [ID " << track_id << "] 锁定共识车牌: " << final_result << std::endl;

                    if (!state.was_snapshot) {
                        std::string base_name = snapshot_dir + "/ID" + std::to_string(track_id) + "_" + final_result;
                        cv::Mat capture_img = raw_full_frame.clone();
                        cv::rectangle(capture_img, vehicle_rect, cv::Scalar(255, 0, 0), 4);
                        
                        std::vector<cv::Point> int_pts;
                        for (auto& p : exp_rect) int_pts.push_back(cv::Point(p.x, p.y));
                        std::vector<std::vector<cv::Point>> polys = { int_pts };
                        cv::polylines(capture_img, polys, true, cv::Scalar(0, 255, 0), 2);

                        cv::imwrite(base_name + "_full.jpg", capture_img);
                        cv::imwrite(base_name + "_plate.jpg", flattened_plate);
                        state.was_snapshot = true;
                    }
                } else {
                    cv::rectangle(orig_img, vehicle_rect, cv::Scalar(0, 165, 255), 2);
                    cv::putText(orig_img, "ID:" + std::to_string(track_id) + " Seeking...",
                                cv::Point(vx1, vy1 - 10), cv::FONT_HERSHEY_SIMPLEX, 0.8, cv::Scalar(0, 165, 255), 2);
                }
            }
        }

        // [阶段四] 兜底清理
        for (auto it = vehicle_states.begin(); it != vehicle_states.end(); ) {
            int t_id = it->first; VehicleState& state = it->second;
            if (std::find(current_frame_track_ids.begin(), current_frame_track_ids.end(), t_id) == current_frame_track_ids.end()) {
                if (!state.was_snapshot && !state.last_frame.empty()) {
                    std::string best_text; int vote_count;
                    voter.get_best_guess(t_id, best_text, vote_count);
                    if (!best_text.empty() && best_text.length() >= 7) {
                        std::cout << "⚠️ [ID " << t_id << "] 目标丢失，触发兜底抓拍！" << std::endl;
                        std::string base_name = snapshot_dir + "/ID" + std::to_string(t_id) + "_" + best_text + "_fallback";
                        cv::Mat capture_img = state.last_frame.clone();
                        cv::rectangle(capture_img, state.last_box, cv::Scalar(0, 165, 255), 4);
                        cv::imwrite(base_name + "_full.jpg", capture_img);
                        cv::imwrite(base_name + "_plate.jpg", state.last_flattened_plate);
                    }
                }
                voter.remove_record(t_id);
                it = vehicle_states.erase(it);
            } else {
                ++it;
            }
        }

        rknn_outputs_release(ctx_vehicle, io_num_vehicle.n_output, outputs);
        
        // 渲染 FPS
        double current_fps = 1000.0 / std::chrono::duration<double, std::milli>(std::chrono::high_resolution_clock::now() - start).count();
        cv::putText(orig_img, "FPS: " + std::to_string(current_fps).substr(0, 5), cv::Point(20, 40), cv::FONT_HERSHEY_SIMPLEX, 1.0, cv::Scalar(0, 0, 255), 2);
        
        cv::imwrite("/tmp/frame_tmp.jpg", orig_img);
        rename("/tmp/frame_tmp.jpg", "/tmp/frame.jpg");
        
        if (frame_count % 30 == 0) std::cout << "--> 当前帧率: " << current_fps << " FPS" << std::endl;
    }

    cap.release();
    rknn_destroy(ctx_vehicle); rknn_destroy(ctx_plate); rknn_destroy(ctx_rec);
    std::cout << "🎉 视频处理完毕！资源安全释放。" << std::endl;
    return 0;
}
