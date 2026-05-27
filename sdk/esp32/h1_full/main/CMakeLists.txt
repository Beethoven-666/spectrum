idf_component_register(
    SRCS "main.cpp"
    INCLUDE_DIRS "."
    REQUIRES h1_sdk pthread esp_driver_uart
)
