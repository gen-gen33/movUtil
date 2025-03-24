import sys
import os
import cv2
import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QLabel, QVBoxLayout, 
                            QHBoxLayout, QWidget, QPushButton, QSlider, 
                            QFileDialog, QSpinBox, QComboBox, QGroupBox,
                            QGridLayout, QCheckBox, QMessageBox, QAction,
                            QDialog, QListWidget, QRadioButton, QButtonGroup)
from PyQt5.QtGui import QImage, QPixmap, QIcon, QDragEnterEvent, QDropEvent
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QMutex, QUrl
import threading
import queue
import time
from PIL import Image
import tifffile
from typing import List, Dict, Union, Optional, Tuple

class VideoLoaderThread(QThread):
    frame_loaded = pyqtSignal(np.ndarray, int)
    loading_finished = pyqtSignal(int, int)  # total_frames, fps
    error_occurred = pyqtSignal(str)
    
    def __init__(self, file_path: str, buffer_size: int = 30, start_frame: int = 0):
        super().__init__()
        self.file_path = file_path
        self.buffer_size = buffer_size
        self.stopped = False
        self.mutex = QMutex()
        self.frame_queue = queue.Queue(maxsize=buffer_size)
        self.total_frames = 0
        self.fps = 30  # Default FPS
        self.current_frame_index = start_frame
        self.file_extension = os.path.splitext(file_path)[1].lower()
        
    def run(self):
        try:
            if self.file_extension in ['.tif', '.tiff']:
                self._load_tiff()
            else:
                self._load_video()
        except Exception as e:
            self.error_occurred.emit(f"Error loading file: {str(e)}")
    
    def _load_video(self):
        cap = cv2.VideoCapture(self.file_path)
        if not cap.isOpened():
            self.error_occurred.emit(f"Could not open video file: {self.file_path}")
            return
            
        self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = cap.get(cv2.CAP_PROP_FPS)
        if self.fps <= 0:
            self.fps = 30  # Default to 30 FPS if not available
            
        # Seek to the requested start frame
        if self.current_frame_index > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame_index)
        
        # Always emit loading_finished to update total frames and FPS
        self.loading_finished.emit(self.total_frames, int(self.fps))
        
        while not self.stopped:
            ret, frame = cap.read()
            if not ret:
                # Reached the end, loop back to the beginning
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                self.current_frame_index = 0
                continue
                
            # Convert BGR to RGB
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Wait if the buffer is full
            while not self.stopped and self.frame_queue.full():
                time.sleep(0.01)
                
            if not self.stopped:
                # Put the frame in the queue with its actual frame index
                self.frame_queue.put((frame, self.current_frame_index))
                self.current_frame_index = (self.current_frame_index + 1) % self.total_frames
                
        cap.release()
    
    def _load_tiff(self):
        try:
            # Open the TIFF file
            tiff = tifffile.TiffFile(self.file_path)
            self.total_frames = len(tiff.pages)
            self.loading_finished.emit(self.total_frames, self.fps)
            
            # Load frames in a separate thread to avoid blocking
            def load_frames():
                i = self.current_frame_index
                while not self.stopped:
                    if self.stopped:
                        break
                        
                    # Read the frame
                    frame = tiff.pages[i].asarray()
                    
                    # Convert to RGB if needed
                    if len(frame.shape) == 2:  # Grayscale
                        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
                    elif frame.shape[2] == 4:  # RGBA
                        frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2RGB)
                    
                    # Wait if the buffer is full
                    while not self.stopped and self.frame_queue.full():
                        time.sleep(0.01)
                        
                    if not self.stopped:
                        self.frame_queue.put((frame, i))
                        i = (i + 1) % self.total_frames
                        
            # Start loading frames in a separate thread
            threading.Thread(target=load_frames, daemon=True).start()
            
        except Exception as e:
            self.error_occurred.emit(f"Error loading TIFF file: {str(e)}")
    
    def get_frame(self) -> Tuple[Optional[np.ndarray], int]:
        if not self.frame_queue.empty():
            return self.frame_queue.get()
        return None, -1
    
    def stop(self):
        self.stopped = True
        self.wait()

class VideoPlayerWindow(QMainWindow):
    frame_updated = pyqtSignal()
    
    def __init__(self, file_path: str = None, parent=None, sync_group: Optional['SyncGroup'] = None):
        super().__init__(parent)
        self.file_path = file_path
        self.sync_group = sync_group
        
        # Video playback variables
        self.current_frame = None
        self.current_frame_index = 0
        self.total_frames = 0
        self.fps = 30
        self.playback_speed = 1.0
        self.is_playing = False
        self.loader_thread = None
        self.last_update_time = time.time()
        self.frame_update_pending = False
        
        # Initialize UI
        self.init_ui()
        
        # Set up the timer for playback
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        
        # Load video if path is provided
        if file_path:
            self.load_video(file_path)
    
    def init_ui(self):
        # Set window properties
        self.setWindowTitle("Video Player")
        self.setMinimumSize(800, 600)
        # Center the window on the screen
        self.center_on_screen()
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #2D2D30;
                color: #E0E0E0;
            }
            QLabel {
                color: #E0E0E0;
            }
            QPushButton {
                background-color: #007ACC;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1C97EA;
            }
            QPushButton:pressed {
                background-color: #0062A3;
            }
            QPushButton:disabled {
                background-color: #555555;
                color: #888888;
            }
            QSlider::groove:horizontal {
                border: 1px solid #999999;
                height: 8px;
                background: #3D3D3D;
                margin: 2px 0;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #007ACC;
                border: 1px solid #5c5c5c;
                width: 18px;
                margin: -8px 0;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background: #1C97EA;
            }
            QSpinBox {
                background-color: #3D3D3D;
                color: #E0E0E0;
                border: 1px solid #555555;
                padding: 4px;
                border-radius: 4px;
            }
            QGroupBox {
                border: 1px solid #555555;
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top center;
                padding: 0 3px;
                color: #E0E0E0;
            }
        """)
        
        # Create central widget and layout
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Create video display area
        self.video_label = QLabel("Drag & Drop Video File Here")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("""
            background-color: #1E1E1E; 
            color: #AAAAAA;
            border-radius: 8px;
            font-size: 16px;
            font-weight: bold;
        """)
        self.video_label.setAcceptDrops(True)
        self.video_label.dragEnterEvent = self.dragEnterEvent
        self.video_label.dropEvent = self.dropEvent
        
        # Create control panel
        control_panel = QWidget()
        control_layout = QVBoxLayout(control_panel)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(10)
        
        # Frame slider with frame labels
        slider_layout = QHBoxLayout()
        self.current_frame_display = QLabel("0")
        self.total_frames_display = QLabel("0")
        
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setMinimum(0)
        self.frame_slider.setMaximum(100)  # Will be updated when video is loaded
        self.frame_slider.valueChanged.connect(self.slider_changed)
        
        slider_layout.addWidget(self.current_frame_display)
        slider_layout.addWidget(self.frame_slider, 1)
        slider_layout.addWidget(self.total_frames_display)
        
        # Playback controls
        playback_layout = QHBoxLayout()
        
        # Create stylish buttons with icons (using text for now, can be replaced with icons)
        self.prev_frame_button = QPushButton("⏮")
        self.prev_frame_button.setToolTip("Previous Frame")
        self.prev_frame_button.clicked.connect(self.prev_frame)
        self.prev_frame_button.setFixedSize(40, 40)
        self.prev_frame_button.setStyleSheet("font-size: 16px;")
        
        self.play_button = QPushButton("▶")
        self.play_button.setToolTip("Play/Pause")
        self.play_button.clicked.connect(self.toggle_playback)
        self.play_button.setFixedSize(60, 40)
        self.play_button.setStyleSheet("font-size: 20px;")
        
        self.next_frame_button = QPushButton("⏭")
        self.next_frame_button.setToolTip("Next Frame")
        self.next_frame_button.clicked.connect(self.next_frame)
        self.next_frame_button.setFixedSize(40, 40)
        self.next_frame_button.setStyleSheet("font-size: 16px;")
        
        # Frame counter and FPS control in a group
        info_layout = QHBoxLayout()
        
        # Frame counter
        frame_group = QGroupBox("Frame Information")
        frame_layout = QVBoxLayout(frame_group)
        self.frame_label = QLabel("Frame: 0 / 0")
        frame_layout.addWidget(self.frame_label)
        
        # FPS control
        fps_group = QGroupBox("Playback Speed")
        fps_layout = QHBoxLayout(fps_group)
        fps_layout.addWidget(QLabel("FPS:"))
        self.fps_spinbox = QSpinBox()
        self.fps_spinbox.setRange(1, 120)
        self.fps_spinbox.setValue(30)
        self.fps_spinbox.valueChanged.connect(self.fps_changed)
        fps_layout.addWidget(self.fps_spinbox)
        
        # Add buttons to playback layout
        playback_layout.addStretch()
        playback_layout.addWidget(self.prev_frame_button)
        playback_layout.addWidget(self.play_button)
        playback_layout.addWidget(self.next_frame_button)
        playback_layout.addStretch()
        
        # Add groups to info layout
        info_layout.addWidget(frame_group)
        info_layout.addWidget(fps_group)
        
        # Add layouts to control panel
        control_layout.addLayout(slider_layout)
        control_layout.addLayout(playback_layout)
        control_layout.addLayout(info_layout)
        
        # Add widgets to main layout
        main_layout.addWidget(self.video_label, 1)
        main_layout.addWidget(control_panel)
        
        self.setCentralWidget(central_widget)
    
    def center_on_screen(self):
        screen_geometry = QApplication.desktop().availableGeometry()
        screen_width = screen_geometry.width()
        screen_height = screen_geometry.height()
        size = self.geometry()
        x = (screen_width - size.width()) // 2
        y = (screen_height - size.height()) // 2
        self.move(x, y)
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    
    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            self.load_video(file_path)
    
    def load_video(self, file_path: str):
        # Stop current playback if any
        self.stop_playback()
        
        # Update window title
        self.setWindowTitle(f"Video Player - {os.path.basename(file_path)}")
        self.file_path = file_path
        
        # Initialize and start the loader thread
        self.loader_thread = VideoLoaderThread(file_path)
        self.loader_thread.loading_finished.connect(self._on_loading_finished_preserve_position)
        self.loader_thread.error_occurred.connect(self.on_error)
        self.loader_thread.start()
        
        # Start playback
        self.start_playback()
    
    def on_loading_finished(self, total_frames: int, fps: int):
        self.total_frames = total_frames
        self.fps = fps
        self.fps_spinbox.setValue(fps)
        
        # Update slider maximum
        self.frame_slider.setMaximum(total_frames - 1)
        
        # Update slider value to 0
        self.frame_slider.setValue(0)
        
        # Update frame display labels
        self.total_frames_display.setText(str(total_frames - 1))
        self.current_frame_display.setText("0")
    
    def on_error(self, error_message: str):
        QMessageBox.critical(self, "Error", error_message)
    
    def update_frame(self):
        if not self.loader_thread:
            return
            
        # Limit frame updates to improve performance
        current_time = time.time()
        if current_time - self.last_update_time < 0.01 and self.frame_update_pending:
            return
            
        self.frame_update_pending = True
        self.last_update_time = current_time
            
        frame, frame_index = self.loader_thread.get_frame()
        if frame is not None:
            self.current_frame = frame
            self.current_frame_index = frame_index
            
            # Update the display
            self.display_frame(frame)
            
            # Update slider and label without triggering events
            self.frame_slider.blockSignals(True)
            self.frame_slider.setValue(frame_index)
            self.frame_slider.blockSignals(False)
            
            self.frame_label.setText(f"Frame: {frame_index} / {self.total_frames - 1}")
            
            # Update current frame display
            self.current_frame_display.setText(str(frame_index))
            
            # Emit frame updated signal
            self.frame_updated.emit()
            
            # Sync with other players if in a sync group
            if self.sync_group and self.sync_group.is_master(self):
                self.sync_group.sync_to_frame(frame_index)
        
        self.frame_update_pending = False
    
    def display_frame(self, frame: np.ndarray):
        # Optimize frame processing
        try:
            # Convert directly without normalization for better performance
            # Only normalize if needed (e.g., for specific image types)
            if frame.dtype != np.uint8:
                if frame.max() != frame.min():  # Avoid division by zero
                    normalized_frame = (frame - frame.min()) / (frame.max() - frame.min()) * 255
                    frame = normalized_frame.astype(np.uint8)
                else:
                    frame = np.zeros_like(frame, dtype=np.uint8)
            
            # Ensure the frame is in the correct format (RGB)
            if len(frame.shape) == 2:  # Grayscale
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
            elif frame.shape[2] == 1:  # Single channel
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
            elif frame.shape[2] == 4:  # RGBA
                frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2RGB)
            
            h, w, ch = frame.shape
            bytes_per_line = ch * w
            
            # Convert the frame to QImage
            q_img = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
            
            # Scale the image to fit the label while maintaining aspect ratio
            pixmap = QPixmap.fromImage(q_img)
            
            # Use FastTransformation for better performance
            scaled_pixmap = pixmap.scaled(self.video_label.size(), 
                                         Qt.KeepAspectRatio, 
                                         Qt.FastTransformation)
            
            # Display the image
            self.video_label.setPixmap(scaled_pixmap)
        except Exception as e:
            print(f"Error displaying frame: {e}")
    
    def toggle_playback(self):
        if self.is_playing:
            self.stop_playback()
        else:
            self.start_playback()
    
    def start_playback(self):
        if not self.loader_thread:
            return
            
        self.is_playing = True
        self.play_button.setText("⏸")
        self.play_button.setToolTip("Pause")
        
        # Calculate timer interval based on FPS and playback speed
        interval = int(1000 / (self.fps * self.playback_speed))
        self.timer.start(interval)
        
        # Notify sync group if master
        if self.sync_group and self.sync_group.is_master(self):
            self.sync_group.set_playing(True)
    
    def stop_playback(self):
        self.is_playing = False
        self.play_button.setText("▶")
        self.play_button.setToolTip("Play")
        self.timer.stop()
        
        # Notify sync group if master
        if self.sync_group and self.sync_group.is_master(self):
            self.sync_group.set_playing(False)
    
    def next_frame(self):
        if not self.loader_thread:
            return
            
        # Pause playback
        was_playing = self.is_playing
        if was_playing:
            self.stop_playback()
        
        # Calculate the next frame index
        next_frame_index = self.current_frame_index + 1
        if next_frame_index >= self.total_frames:
            next_frame_index = 0  # Loop back to the beginning
        
        # Seek to the next frame
        self._seek_to_frame(next_frame_index)
        
        # Resume playback if it was playing
        if was_playing:
            self.start_playback()
    
    def prev_frame(self):
        if not self.loader_thread or self.current_frame_index <= 0:
            return
            
        # Pause playback
        was_playing = self.is_playing
        if was_playing:
            self.stop_playback()
        
        # Calculate the previous frame index
        prev_frame_index = self.current_frame_index - 1
        if prev_frame_index < 0:
            prev_frame_index = self.total_frames - 1  # Loop back to the end
        
        # Seek to the previous frame
        self._seek_to_frame(prev_frame_index)
        
        # Resume playback if it was playing
        if was_playing:
            self.start_playback()
    
    def slider_changed(self):
        if not self.loader_thread or self.total_frames == 0:
            return
            
        # Get the frame index from the slider
        frame_index = self.frame_slider.value()
        
        # Update current frame display
        self.current_frame_display.setText(str(frame_index))
        
        # Only seek if the frame index has actually changed
        if frame_index != self.current_frame_index:
            # Pause playback temporarily
            was_playing = self.is_playing
            if was_playing:
                self.stop_playback()
                
            # Seek to the requested frame
            self._seek_to_frame(frame_index)
            
            # Resume playback if it was playing
            if was_playing:
                self.start_playback()
    
    def _seek_to_frame(self, frame_index):
        # Stop current loader thread
        if self.loader_thread:
            self.loader_thread.stop()
            
        # Create a new loader thread starting at the requested frame
        self.loader_thread = VideoLoaderThread(self.file_path, start_frame=frame_index)
        
        # Connect signals but don't call on_loading_finished directly
        # Instead, use a custom slot that preserves the frame position
        self.loader_thread.loading_finished.connect(self._on_loading_finished_preserve_position)
        self.loader_thread.error_occurred.connect(self.on_error)
        self.loader_thread.start()
        
        # Update frame label and current frame index
        self.frame_label.setText(f"Frame: {frame_index} / {self.total_frames - 1}")
        self.current_frame_index = frame_index
        
        # Immediately get and display the first frame after seeking
        # This ensures the display updates immediately without needing to click play
        QTimer.singleShot(100, self._update_after_seek)
    
    def _update_after_seek(self):
        """Update the display with the current frame after seeking"""
        if not self.loader_thread:
            return
            
        # Try to get the frame a few times, as it might take a moment to load
        for _ in range(5):
            frame, frame_index = self.loader_thread.get_frame()
            if frame is not None:
                self.current_frame = frame
                self.current_frame_index = frame_index
                
                # Update the display
                self.display_frame(frame)
                return
            
            # Wait a bit for the frame to load
            QApplication.processEvents()
            time.sleep(0.05)
    
    def _on_loading_finished_preserve_position(self, total_frames: int, fps: int):
        """Custom version of on_loading_finished that preserves the current frame position"""
        self.total_frames = total_frames
        self.fps = fps
        self.fps_spinbox.setValue(fps)
        
        # Update slider maximum without changing current position
        self.frame_slider.setMaximum(total_frames - 1)
        
        # Don't reset the slider value to 0, keep the current position
        # Only update the total frames display
        self.total_frames_display.setText(str(total_frames - 1))
    
    def fps_changed(self):
        new_fps = self.fps_spinbox.value()
        self.fps = new_fps
        
        # Update timer interval if playing
        if self.is_playing:
            interval = int(1000 / (self.fps * self.playback_speed))
            self.timer.start(interval)
            
        # Notify sync group if master
        if self.sync_group and self.sync_group.is_master(self):
            self.sync_group.set_fps(new_fps)
    
    def set_sync_frame(self, frame_index: int):
        """Set the frame index from a sync group master"""
        if not self.loader_thread or frame_index == self.current_frame_index:
            return
            
        # Pause playback temporarily
        was_playing = self.is_playing
        if was_playing:
            self.stop_playback()
        
        # Seek to the requested frame
        self._seek_to_frame(frame_index)
        
        # Resume playback if it was playing and the master is playing
        if was_playing and self.sync_group and self.sync_group.master and self.sync_group.master.is_playing:
            self.start_playback()
    
    def set_sync_playing(self, is_playing: bool):
        # Called by sync group to synchronize playback state
        if is_playing and not self.is_playing:
            self.start_playback()
        elif not is_playing and self.is_playing:
            self.stop_playback()
    
    def set_sync_fps(self, fps: int):
        # Called by sync group to synchronize FPS
        self.fps_spinbox.setValue(fps)
    
    def closeEvent(self, event):
        # Clean up resources
        if self.loader_thread:
            self.loader_thread.stop()
        
        # Remove from sync group if part of one
        if self.sync_group:
            self.sync_group.remove_player(self)
            
        event.accept()

class SyncGroup:
    def __init__(self):
        self.players: List[VideoPlayerWindow] = []
        self.master: Optional[VideoPlayerWindow] = None
    
    def add_player(self, player: VideoPlayerWindow):
        self.players.append(player)
        if not self.master:
            self.set_master(player)
    
    def remove_player(self, player: VideoPlayerWindow):
        if player in self.players:
            self.players.remove(player)
            
        # If master was removed, set a new master if any players remain
        if player == self.master and self.players:
            self.set_master(self.players[0])
        elif not self.players:
            self.master = None
    
    def set_master(self, player: VideoPlayerWindow):
        self.master = player
    
    def is_master(self, player: VideoPlayerWindow) -> bool:
        return player == self.master
    
    def sync_to_frame(self, frame_index: int):
        for player in self.players:
            if player != self.master:
                player.set_sync_frame(frame_index)
    
    def set_playing(self, is_playing: bool):
        for player in self.players:
            if player != self.master:
                player.set_sync_playing(is_playing)
    
    def set_fps(self, fps: int):
        for player in self.players:
            if player != self.master:
                player.set_sync_fps(fps)

class OverlayManager:
    def __init__(self):
        self.main_player: Optional[VideoPlayerWindow] = None
        self.overlay_player: Optional[VideoPlayerWindow] = None
        self.blend_mode: str = "Normal"  # Normal, Add, Multiply, Screen, Difference
        self.opacity: float = 0.5  # 0.0 to 1.0
        self.is_active: bool = False
    
    def set_main_player(self, player: 'VideoPlayerWindow'):
        self.main_player = player
    
    def set_overlay_player(self, player: 'VideoPlayerWindow'):
        self.overlay_player = player
    
    def set_blend_mode(self, mode: str):
        self.blend_mode = mode
    
    def set_opacity(self, opacity: float):
        self.opacity = max(0.0, min(1.0, opacity))
    
    def activate(self):
        self.is_active = True
        if self.main_player and self.overlay_player:
            # Connect signals for frame updates
            self.main_player.frame_updated.connect(self.update_overlay)
    
    def deactivate(self):
        self.is_active = False
        if self.main_player:
            # Disconnect signals
            try:
                self.main_player.frame_updated.disconnect(self.update_overlay)
            except TypeError:
                # Signal was not connected
                pass
    
    def update_overlay(self):
        if not self.is_active or not self.main_player or not self.overlay_player:
            return
        
        if self.main_player.current_frame is not None and self.overlay_player.current_frame is not None:
            # Blend frames
            blended_frame = self.blend_frames(
                self.main_player.current_frame,
                self.overlay_player.current_frame,
                self.blend_mode,
                self.opacity
            )
            
            # Display the blended frame
            self.main_player.display_frame(blended_frame)
    
    def blend_frames(self, main_frame: np.ndarray, overlay_frame: np.ndarray, 
                     blend_mode: str, opacity: float) -> np.ndarray:
        # Create a copy of the main frame to avoid modifying the original
        result = main_frame.copy()
        
        # Get dimensions
        main_h, main_w = main_frame.shape[:2]
        overlay_h, overlay_w = overlay_frame.shape[:2]
        
        # Calculate the visible area of the overlay frame
        visible_h = min(main_h, overlay_h)
        visible_w = min(main_w, overlay_w)
        
        # Get the visible portion of the overlay frame
        overlay_visible = overlay_frame[:visible_h, :visible_w]
        
        # Apply blend mode to the visible area
        if blend_mode == "Normal":
            # Simple alpha blending
            result[:visible_h, :visible_w] = (
                (1 - opacity) * result[:visible_h, :visible_w] + 
                opacity * overlay_visible
            ).astype(np.uint8)
        
        elif blend_mode == "Add":
            # Additive blending
            added = result[:visible_h, :visible_w] + overlay_visible * opacity
            result[:visible_h, :visible_w] = np.clip(added, 0, 255).astype(np.uint8)
        
        elif blend_mode == "Multiply":
            # Multiply blending
            multiplied = result[:visible_h, :visible_w] * (1 - opacity + opacity * overlay_visible / 255)
            result[:visible_h, :visible_w] = np.clip(multiplied, 0, 255).astype(np.uint8)
        
        elif blend_mode == "Screen":
            # Screen blending
            inverted_main = 255 - result[:visible_h, :visible_w]
            inverted_overlay = 255 - overlay_visible
            screened = 255 - (inverted_main * (1 - opacity + opacity * inverted_overlay / 255))
            result[:visible_h, :visible_w] = np.clip(screened, 0, 255).astype(np.uint8)
        
        elif blend_mode == "Difference":
            # Difference blending
            diff = np.abs(result[:visible_h, :visible_w] - overlay_visible)
            result[:visible_h, :visible_w] = (result[:visible_h, :visible_w] * (1 - opacity) + 
                                             diff * opacity).astype(np.uint8)
        
        return result

class OverlayDialog(QDialog):
    def __init__(self, parent, players):
        super().__init__(parent)
        self.players = players
        self.selected_main = None
        self.selected_overlay = None
        self.blend_mode = "Normal"
        self.opacity = 0.5
        
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("オーバーレイ設定")
        self.setMinimumSize(400, 500)
        self.setStyleSheet("""
            QDialog {
                background-color: #2D2D30;
                color: #E0E0E0;
            }
            QLabel {
                color: #E0E0E0;
                font-size: 14px;
            }
            QPushButton {
                background-color: #007ACC;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1C97EA;
            }
            QPushButton:pressed {
                background-color: #0062A3;
            }
            QRadioButton {
                color: #E0E0E0;
                font-size: 14px;
            }
            QListWidget {
                background-color: #1E1E1E;
                color: #E0E0E0;
                border: 1px solid #3E3E40;
                border-radius: 4px;
            }
            QListWidget::item:selected {
                background-color: #007ACC;
            }
            QGroupBox {
                border: 1px solid #555555;
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
                color: #E0E0E0;
            }
            QComboBox {
                background-color: #3D3D3D;
                color: #E0E0E0;
                border: 1px solid #555555;
                padding: 4px;
                border-radius: 4px;
            }
            QSlider::groove:horizontal {
                border: 1px solid #999999;
                height: 8px;
                background: #3D3D3D;
                margin: 2px 0;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #007ACC;
                border: 1px solid #5c5c5c;
                width: 18px;
                margin: -8px 0;
                border-radius: 9px;
            }
        """)
        
        layout = QVBoxLayout(self)
        
        # Player selection section
        player_group = QGroupBox("プレーヤー選択")
        player_layout = QVBoxLayout(player_group)
        
        # Main player selection
        main_label = QLabel("メインプレーヤー:")
        self.main_list = QListWidget()
        for i, player in enumerate(self.players):
            self.main_list.addItem(f"プレーヤー {i+1}: {os.path.basename(player.file_path)}")
        
        # Overlay player selection
        overlay_label = QLabel("オーバーレイプレーヤー:")
        self.overlay_list = QListWidget()
        for i, player in enumerate(self.players):
            self.overlay_list.addItem(f"プレーヤー {i+1}: {os.path.basename(player.file_path)}")
        
        player_layout.addWidget(main_label)
        player_layout.addWidget(self.main_list)
        player_layout.addWidget(overlay_label)
        player_layout.addWidget(self.overlay_list)
        
        # Blend mode selection
        blend_group = QGroupBox("ブレンドモード")
        blend_layout = QVBoxLayout(blend_group)
        
        self.blend_combo = QComboBox()
        self.blend_combo.addItems(["Normal", "Add", "Multiply", "Screen", "Difference"])
        blend_layout.addWidget(self.blend_combo)
        
        # Opacity slider with 10% steps
        opacity_group = QGroupBox("不透明度")
        opacity_layout = QVBoxLayout(opacity_group)
        
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setMinimum(0)
        self.opacity_slider.setMaximum(10)  # 0% to 100% in 10% steps
        self.opacity_slider.setValue(5)     # Default 50%
        self.opacity_slider.setTickPosition(QSlider.TicksBelow)
        self.opacity_slider.setTickInterval(1)
        
        self.opacity_label = QLabel("50%")
        self.opacity_label.setAlignment(Qt.AlignCenter)
        
        opacity_layout.addWidget(self.opacity_slider)
        opacity_layout.addWidget(self.opacity_label)
        
        # Connect signals
        self.opacity_slider.valueChanged.connect(self.update_opacity_label)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.apply_button = QPushButton("適用")
        self.cancel_button = QPushButton("キャンセル")
        
        self.apply_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        
        button_layout.addWidget(self.apply_button)
        button_layout.addWidget(self.cancel_button)
        
        # Add all sections to main layout
        layout.addWidget(player_group)
        layout.addWidget(blend_group)
        layout.addWidget(opacity_group)
        layout.addLayout(button_layout)
    
    def update_opacity_label(self, value):
        self.opacity_label.setText(f"{value * 10}%")
        self.opacity = value / 10.0
    
    def get_selections(self):
        main_idx = self.main_list.currentRow()
        overlay_idx = self.overlay_list.currentRow()
        
        if main_idx >= 0 and main_idx < len(self.players):
            self.selected_main = self.players[main_idx]
        
        if overlay_idx >= 0 and overlay_idx < len(self.players):
            self.selected_overlay = self.players[overlay_idx]
        
        self.blend_mode = self.blend_combo.currentText()
        
        return {
            "main_player": self.selected_main,
            "overlay_player": self.selected_overlay,
            "blend_mode": self.blend_mode,
            "opacity": self.opacity
        }

class OverlayControlPanel(QWidget):
    def __init__(self, parent, overlay_manager):
        super().__init__(parent)
        self.overlay_manager = overlay_manager
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Title
        title_label = QLabel("オーバーレイコントロール")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        title_label.setAlignment(Qt.AlignCenter)
        
        # Blend mode selection
        blend_group = QGroupBox("ブレンドモード")
        blend_layout = QVBoxLayout(blend_group)
        
        self.blend_combo = QComboBox()
        self.blend_combo.addItems(["Normal", "Add", "Multiply", "Screen", "Difference"])
        self.blend_combo.setCurrentText(self.overlay_manager.blend_mode)
        self.blend_combo.currentTextChanged.connect(self.change_blend_mode)
        blend_layout.addWidget(self.blend_combo)
        
        # Opacity slider with 10% steps
        opacity_group = QGroupBox("不透明度")
        opacity_layout = QVBoxLayout(opacity_group)
        
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setMinimum(0)
        self.opacity_slider.setMaximum(10)  # 0% to 100% in 10% steps
        self.opacity_slider.setValue(int(self.overlay_manager.opacity * 10))
        self.opacity_slider.setTickPosition(QSlider.TicksBelow)
        self.opacity_slider.setTickInterval(1)
        
        self.opacity_label = QLabel(f"{int(self.overlay_manager.opacity * 100)}%")
        self.opacity_label.setAlignment(Qt.AlignCenter)
        
        opacity_layout.addWidget(self.opacity_slider)
        opacity_layout.addWidget(self.opacity_label)
        
        # Connect signals
        self.opacity_slider.valueChanged.connect(self.change_opacity)
        
        # Toggle button
        self.toggle_button = QPushButton("オーバーレイ無効化")
        self.toggle_button.clicked.connect(self.toggle_overlay)
        
        # Add all sections to main layout
        layout.addWidget(title_label)
        layout.addWidget(blend_group)
        layout.addWidget(opacity_group)
        layout.addWidget(self.toggle_button)
        layout.addStretch()
        
        # Set initial state
        self.update_toggle_button()
    
    def change_blend_mode(self, mode):
        self.overlay_manager.set_blend_mode(mode)
    
    def change_opacity(self, value):
        opacity = value / 10.0
        self.opacity_label.setText(f"{int(opacity * 100)}%")
        self.overlay_manager.set_opacity(opacity)
    
    def toggle_overlay(self):
        if self.overlay_manager.is_active:
            self.overlay_manager.deactivate()
        else:
            self.overlay_manager.activate()
        self.update_toggle_button()
    
    def update_toggle_button(self):
        if self.overlay_manager.is_active:
            self.toggle_button.setText("オーバーレイ無効化")
        else:
            self.toggle_button.setText("オーバーレイ有効化")

class MainApplication(QMainWindow):
    def __init__(self):
        super().__init__()
        self.players: List[VideoPlayerWindow] = []
        self.sync_group = SyncGroup()
        self.overlay_manager = OverlayManager()
        
        # Initialize UI
        self.init_ui()
    
    def init_ui(self):
        # Set window properties - smaller size and always on top
        self.setWindowTitle("動画再生")
        self.setMinimumSize(300, 200)
        self.setMaximumSize(400, 300)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        # Position the window in the top-left corner of the screen
        self.move(0, 0)
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #2D2D30;
                color: #E0E0E0;
            }
            QLabel {
                color: #E0E0E0;
                font-size: 14px;
            }
            QPushButton {
                background-color: #007ACC;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1C97EA;
            }
            QPushButton:pressed {
                background-color: #0062A3;
            }
            QPushButton:disabled {
                background-color: #555555;
                color: #888888;
            }
            QCheckBox {
                color: #E0E0E0;
                font-size: 14px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
            QCheckBox::indicator:checked {
                background-color: #007ACC;
                border: 2px solid #E0E0E0;
                border-radius: 3px;
            }
            QMenuBar {
                background-color: #2D2D30;
                color: #E0E0E0;
            }
            QMenuBar::item {
                background-color: transparent;
                padding: 4px 10px;
            }
            QMenuBar::item:selected {
                background-color: #3E3E40;
            }
            QMenu {
                background-color: #2D2D30;
                color: #E0E0E0;
                border: 1px solid #3E3E40;
            }
            QMenu::item:selected {
                background-color: #3E3E40;
            }
        """)
        
        # Create menu bar
        menubar = self.menuBar()
        file_menu = menubar.addMenu('ファイル')
        
        # Add open action to menu
        open_action = QAction('ファイルを開く', self)
        open_action.setShortcut('Ctrl+O')
        open_action.triggered.connect(self.open_video)
        file_menu.addAction(open_action)
        
        # Add overlay action to menu
        overlay_action = QAction('オーバーレイ設定', self)
        overlay_action.triggered.connect(self.open_overlay_dialog)
        file_menu.addAction(overlay_action)
        
        # Create central widget and layout
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Drop zone - simplified
        drop_zone = QLabel("ここにファイルをドロップ")
        drop_zone.setAlignment(Qt.AlignCenter)
        drop_zone.setStyleSheet("""
            background-color: #1E1E1E;
            border: 2px dashed #555555;
            border-radius: 8px;
            padding: 20px;
            font-size: 14px;
            color: #888888;
        """)
        drop_zone.setMinimumHeight(100)
        
        # Make the main window accept drops
        self.setAcceptDrops(True)
        
        # Sync checkbox in a simple layout
        sync_layout = QHBoxLayout()
        sync_checkbox = QCheckBox("同期再生")
        sync_checkbox.setToolTip("複数の動画を同時に再生します")
        sync_checkbox.stateChanged.connect(self.toggle_sync)
        sync_layout.addWidget(sync_checkbox)
        sync_layout.addStretch()
        
        # Add widgets to main layout
        main_layout.addWidget(drop_zone, 1)
        main_layout.addLayout(sync_layout)
        
        self.setCentralWidget(central_widget)
    
    def open_video(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, 
            "Open Video", 
            "", 
            "Video Files (*.mp4 *.avi *.mov *.mkv *.tif *.tiff);;All Files (*)"
        )
        
        for file_path in file_paths:
            self.create_player(file_path)
    
    def create_player(self, file_path: str):
        # Create a new player window
        sync_group = self.sync_group if self.is_sync_enabled() else None
        player = VideoPlayerWindow(file_path, self, sync_group)
        player.show()
        player.center_on_screen()  # Center the video player window on the screen
        
        # Add to list of players
        self.players.append(player)
        
        # Add to sync group if sync is enabled
        if self.is_sync_enabled():
            self.sync_group.add_player(player)
    
    def is_sync_enabled(self) -> bool:
        # Find the sync checkbox
        for child in self.centralWidget().children():
            if isinstance(child, QCheckBox) and child.text() == "同期再生":
                return child.isChecked()
        return False
    
    def toggle_sync(self, state: int):
        if state == Qt.Checked:
            # Enable synchronization for all players
            for player in self.players:
                player.sync_group = self.sync_group
                self.sync_group.add_player(player)
        else:
            # Disable synchronization for all players
            for player in self.players:
                player.sync_group = None
            
            # Clear the sync group
            self.sync_group = SyncGroup()
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    
    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        for url in urls:
            file_path = url.toLocalFile()
            self.create_player(file_path)
    
    def closeEvent(self, event):
        # Close all player windows
        for player in self.players:
            player.close()
        event.accept()
    
    def open_overlay_dialog(self):
        dialog = OverlayDialog(self, self.players)
        if dialog.exec_() == QDialog.Accepted:
            selections = dialog.get_selections()
            self.overlay_manager.set_main_player(selections["main_player"])
            self.overlay_manager.set_overlay_player(selections["overlay_player"])
            self.overlay_manager.set_blend_mode(selections["blend_mode"])
            self.overlay_manager.set_opacity(selections["opacity"])
            self.overlay_manager.activate()
            self.overlay_control_panel = OverlayControlPanel(self, self.overlay_manager)
            self.overlay_control_panel.show()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    main_app = MainApplication()
    main_app.show()
    sys.exit(app.exec_())
