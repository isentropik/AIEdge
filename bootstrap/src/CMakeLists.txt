set(METER "${CMAKE_CURRENT_LIST_DIR}/../../code")
idf_component_register(SRCS "main.cpp" "${METER}/components/jomjol_fileserver_ota/miniz/miniz.c"
 INCLUDE_DIRS "." "${METER}/main" "${METER}/components/jomjol_fileserver_ota" "${METER}/components/jomjol_flowcontroll"
 REQUIRES driver fatfs sdmmc mbedtls json esp_wifi esp_event esp_netif nvs_flash esp_http_server esp_http_client app_update esp_timer mdns)
