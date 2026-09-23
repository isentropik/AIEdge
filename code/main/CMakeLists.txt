# Refresh identity for every build, including incremental builds.
set(AIEDGE_METADATA_DIR "${CMAKE_BINARY_DIR}/aiedge-metadata")
get_filename_component(AIEDGE_REPO "${CMAKE_SOURCE_DIR}/.." ABSOLUTE)
set(AIEDGE_METADATA_SCRIPT "${CMAKE_SOURCE_DIR}/tools/build_metadata.py")
execute_process(COMMAND "${PYTHON}" "${AIEDGE_METADATA_SCRIPT}"
    --repo "${AIEDGE_REPO}" --output "${AIEDGE_METADATA_DIR}"
    RESULT_VARIABLE metadata_result)
if(NOT metadata_result EQUAL 0)
    message(FATAL_ERROR "Could not generate AIEdge build identity")
endif()
file(GLOB_RECURSE app_sources ${CMAKE_SOURCE_DIR}/main/*.*)
list(FILTER app_sources EXCLUDE REGEX "/version\\.cpp$")
list(APPEND app_sources "${AIEDGE_METADATA_DIR}/version.cpp")
idf_component_register(SRCS ${app_sources} INCLUDE_DIRS "." REQUIRES esp_psram)
add_custom_target(aiedge_build_identity ALL
    COMMAND "${PYTHON}" "${AIEDGE_METADATA_SCRIPT}" --repo "${AIEDGE_REPO}" --output "${AIEDGE_METADATA_DIR}"
    BYPRODUCTS "${AIEDGE_METADATA_DIR}/version.cpp" "${AIEDGE_METADATA_DIR}/version.txt" "${AIEDGE_METADATA_DIR}/build-metadata.json"
    VERBATIM)
add_dependencies(${COMPONENT_LIB} aiedge_build_identity)
