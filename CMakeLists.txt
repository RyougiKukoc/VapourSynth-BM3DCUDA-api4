cmake_minimum_required(VERSION 3.20)

if (POLICY CMP0091)
    cmake_policy(SET CMP0091 NEW)
endif()

project(VapourSynth-BM3DCUDA VERSION 2.15 LANGUAGES CXX)

set(VAPOURSYNTH_INCLUDE_DIRECTORY "" CACHE PATH "Path to VapourSynth headers")
set(USE_NVRTC_STATIC ON CACHE BOOL "Whether to use NVRTC static library")
set(ENABLE_CPU ON CACHE BOOL "Enable CPU build")
set(ENABLE_CUDA OFF CACHE BOOL "Enable standard CUDA build")
set(ENABLE_CUDA_RTC ON CACHE BOOL "Enable CUDA RTC build")
set(ENABLE_HIP OFF CACHE BOOL "Enable HIP build")
set(ENABLE_SYCL OFF CACHE BOOL "Enable SYCL build")

if (ENABLE_CUDA)
    add_subdirectory(source)
endif()

if (ENABLE_CUDA_RTC)
    add_subdirectory(rtc_source)
endif()

if (ENABLE_CPU)
    add_subdirectory(cpu_source)
endif()

if (ENABLE_HIP)
    add_subdirectory(hip_source)
endif()

if (ENABLE_SYCL)
    add_subdirectory(sycl_source)
endif()

