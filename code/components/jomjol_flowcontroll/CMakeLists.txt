FILE(GLOB_RECURSE app_sources ${CMAKE_CURRENT_SOURCE_DIR}/*.*)

idf_component_register(SRCS ${app_sources}
                    INCLUDE_DIRS "."
                    REQUIRES mbedtls json esp_http_client esp_timer esp_wifi jomjol_tfliteclass jomjol_helper jomjol_controlcamera jomjol_mqtt jomjol_influxdb jomjol_webhook jomjol_fileserver_ota jomjol_image_proc jomjol_wlan openmetrics)

# Keep calibrated bicubic/quantized preprocessing consistent with host fixtures.
set_source_files_properties(ClassFlowCNNPolar.cpp PROPERTIES COMPILE_OPTIONS "-ffp-contract=off")


