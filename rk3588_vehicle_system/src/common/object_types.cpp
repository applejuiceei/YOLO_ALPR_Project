#include "common/types.hpp"

namespace vehicle_system {

ObjectType object_type_from_coco(int class_id) {
    switch (class_id) {
        case 0: return ObjectType::Person;
        case 1:
        case 3: return ObjectType::NonMotor;
        case 2: return ObjectType::Car;
        case 5: return ObjectType::Bus;
        case 7: return ObjectType::Truck;
        default: return ObjectType::Unknown;
    }
}

const char* object_type_name(ObjectType type) {
    switch (type) {
        case ObjectType::Person: return "person";
        case ObjectType::Car: return "car";
        case ObjectType::Bus: return "bus";
        case ObjectType::Truck: return "truck";
        case ObjectType::NonMotor: return "non_motor";
        default: return "unknown";
    }
}

}  // namespace vehicle_system

