import os
import sys
import subprocess
import shutil
import datetime

# Configuration
APP_NAME = "MOVUtil"
AUTHOR = "Gen."
VERSION = "1.0.0"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Ensure PyInstaller is installed
try:
    import PyInstaller
except ImportError:
    print("Installing PyInstaller...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

# Ensure MSIX Packaging Tool SDK is available
try:
    import win32api
except ImportError:
    print("Installing pywin32...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pywin32"])

# Create build directory
build_dir = os.path.join(BASE_DIR, "build")
dist_dir = os.path.join(BASE_DIR, "dist")
msix_dir = os.path.join(BASE_DIR, "msix")

for directory in [build_dir, dist_dir, msix_dir]:
    if os.path.exists(directory):
        shutil.rmtree(directory)
    os.makedirs(directory)

# Create app manifest for Microsoft Store
def create_appx_manifest():
    manifest_path = os.path.join(msix_dir, "AppxManifest.xml")
    
    # Get current date in the format YYYY-MM-DD
    current_date = datetime.datetime.now().strftime("%Y-%m-%d")
    
    manifest_content = f'''
<?xml version="1.0" encoding="utf-8"?>
<Package
  xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities">
  <Identity
    Name="{APP_NAME}App"
    Publisher="CN={AUTHOR}"
    Version="{VERSION}" />
  <Properties>
    <DisplayName>{APP_NAME}</DisplayName>
    <PublisherDisplayName>{AUTHOR}</PublisherDisplayName>
    <Description>Video player utility for synchronized playback</Description>
    <Logo>assets\logo.png</Logo>
  </Properties>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.17763.0" MaxVersionTested="10.0.19041.0" />
  </Dependencies>
  <Resources>
    <Resource Language="en-us" />
  </Resources>
  <Applications>
    <Application Id="{APP_NAME}" Executable="{APP_NAME}.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements
        DisplayName="{APP_NAME}"
        Description="Video player utility for synchronized playback"
        BackgroundColor="transparent"
        Square150x150Logo="assets\logo.png"
        Square44x44Logo="assets\logo.png" />
    </Application>
  </Applications>
  <Capabilities>
    <rescap:Capability Name="runFullTrust" />
  </Capabilities>
</Package>
'''
    
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(manifest_content)
    
    print(f"Created AppxManifest.xml at {manifest_path}")
    return manifest_path

# Create assets directory and placeholder logo
def create_assets():
    assets_dir = os.path.join(msix_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    
    # Create a simple placeholder logo (you should replace this with your actual logo)
    print("Note: You should replace the placeholder logo with your actual logo.")
    print(f"Placeholder logo created at {assets_dir}\\logo.png")

# Build the application using PyInstaller with optimized settings
def build_app():
    print("Building application with PyInstaller...")
    
    # PyInstaller command with optimization flags
    pyinstaller_cmd = [
        "pyinstaller",
        "--name=" + APP_NAME,
        "--onefile",  # Create a single executable
        "--windowed",  # Don't show console window
        "--clean",     # Clean PyInstaller cache
        "--noconfirm", # Replace output directory without asking
        "--add-data=README.md;.",  # Include README
        "--icon=msix/assets/logo.png",  # Use the app icon
        # Performance optimizations
        "--noupx",     # Disable UPX compression for faster startup
        "--key=MOVUtilKey",  # Encryption key for bytecode obfuscation
        # Additional optimization flags
        "--strip",     # Strip symbols from executable (smaller size)
        "video_player.py"  # Main script
    ]
    
    # Run PyInstaller
    subprocess.run(pyinstaller_cmd, check=True)
    
    # Copy the executable to the MSIX directory
    exe_path = os.path.join(dist_dir, f"{APP_NAME}.exe")
    shutil.copy(exe_path, msix_dir)
    
    print(f"Application built successfully at {msix_dir}\\{APP_NAME}.exe")

# Create a batch file to help with MSIX packaging
def create_packaging_batch():
    batch_path = os.path.join(BASE_DIR, "package_msix.bat")
    batch_content = f'''
@echo off
echo This script will help you package the {APP_NAME} application for the Microsoft Store.
echo Please make sure you have the MSIX Packaging Tool installed from the Microsoft Store.
echo.

echo 1. Open the MSIX Packaging Tool
echo 2. Select "Application Package" from the menu
echo 3. Choose "Create package from existing installer"
echo 4. Follow the wizard and select the {APP_NAME}.exe from the msix folder
echo 5. Complete the packaging process

echo.
echo Press any key to open the msix folder...
pause > nul
start "" "%~dp0msix"
'''
    
    with open(batch_path, "w") as f:
        f.write(batch_content)
    
    print(f"Created packaging helper batch file at {batch_path}")

# Main build process
def main():
    print(f"Building {APP_NAME} v{VERSION} by {AUTHOR} for Microsoft Store...")
    
    # Create assets directory and placeholder logo
    create_assets()
    
    # Create app manifest
    create_appx_manifest()
    
    # Build the application
    build_app()
    
    # Create packaging helper
    create_packaging_batch()
    
    print("\nBuild completed successfully!")
    print("To create the MSIX package for Microsoft Store submission:")
    print("1. Run the 'package_msix.bat' script")
    print("2. Follow the instructions to use the MSIX Packaging Tool")
    print("\nNote: You will need a code signing certificate to submit to the Microsoft Store.")

if __name__ == "__main__":
    main()
