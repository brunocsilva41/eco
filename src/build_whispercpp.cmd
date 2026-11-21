@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
set "VULKAN_SDK=E:\vulkan"
set "PATH=%PATH%;E:\vulkan\Bin;C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin;C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja"
cd /d F:\Jarvis\work\whispercpp
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=cl -DCMAKE_CXX_COMPILER=cl -DGGML_VULKAN=1 -DWHISPER_BUILD_TESTS=OFF
if errorlevel 1 exit /b 1
cmake --build build -j 2 --target whisper-cli whisper-bench
echo FIM exit=%ERRORLEVEL%
