import subprocess
import sys
import traceback
import json

# Monkey-patch subprocess.Popen to prevent focus shifts on Windows
if sys.platform == 'win32':
    _Popen = subprocess.Popen

    def Popen(*args, **kwargs):
        if kwargs.get('creationflags', None) is None:
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        return _Popen(*args, **kwargs)

    subprocess.Popen = Popen

import threading
import time
import os
import shutil
import numpy as np
import soundcard as sc
import webrtcvad
import speech_recognition as sr
from pydub import AudioSegment, silence
from flask import Flask, render_template, jsonify, request, send_from_directory, abort

# AudioRecorder class definition
class AudioRecorder:
    def __init__(self):
        self.timestamp = int(time.time())
        self.session_folder = f"session_{self.timestamp}"
        os.makedirs(self.session_folder, exist_ok=True)

        # Create the favorites folder if it doesn't exist
        self.favorites_folder = "favorites"
        os.makedirs(self.favorites_folder, exist_ok=True)

        self.is_listening = False
        self.is_recording = False
        self.recordings = []  # List to store recording metadata
        self.favorites = []   # List to store favorites metadata

        self.lock = threading.RLock()  # Use RLock instead of Lock
        self.vad = webrtcvad.Vad()
        self.vad.set_mode(1)  # VAD sensitivity
        self.recognizer = sr.Recognizer()
        self.audio_buffer = bytearray()
        self.silence_duration = 0
        self.MAX_SILENCE_DURATION = 0.5  # Adjust as needed
        # Audio parameters
        self.SAMPLE_RATE = 48000
        self.NUM_CHANNELS = 1
        self.FRAME_DURATION = 20  # ms
        self.FRAME_SIZE = int(self.SAMPLE_RATE * self.FRAME_DURATION / 1000)
        # Prepare devices
        self.loopback_mic = self.get_loopback_microphone()
        if self.loopback_mic is None:
            raise RuntimeError("Could not find loopback microphone for the default speaker.")

        # Load favorites and recordings on startup
        self.load_favorites()
        self.load_recordings()

    def get_loopback_microphone(self):
        default_speaker = sc.default_speaker()
        all_mics = sc.all_microphones(include_loopback=True)
        for mic in all_mics:
            if mic.isloopback and mic.name == default_speaker.name:
                return mic
        return None

    def start(self):
        self.is_listening = True
        self.thread = threading.Thread(target=self.record_loop)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        self.is_listening = False
        self.thread.join()

    def record_loop(self):
        def convert_audio(data):
            # Convert audio data to 16-bit PCM
            if data.shape[1] > 1:
                data = data[:, 0]  # Take first channel if stereo
            else:
                data = data.flatten()
            pcm_data = np.int16(data * 32767).tobytes()
            return pcm_data

        with self.loopback_mic.recorder(samplerate=self.SAMPLE_RATE, channels=[0], exclusive_mode=False) as recorder:
            print("Listening for speech...")
            while self.is_listening:
                data = recorder.record(numframes=self.FRAME_SIZE)
                pcm_data = convert_audio(data)
                is_speech = self.vad.is_speech(pcm_data, self.SAMPLE_RATE)
                if is_speech:
                    self.silence_duration = 0
                    self.audio_buffer.extend(pcm_data)
                    if not self.is_recording:
                        self.is_recording = True
                        print("Speech detected, recording...")
                elif len(self.audio_buffer) > 0:
                    self.silence_duration += self.FRAME_DURATION / 1000.0
                    if self.silence_duration > self.MAX_SILENCE_DURATION:
                        print("Silence detected, processing audio...")
                        self.process_audio_buffer()
                else:
                    pass  # No speech detected

    def process_audio_buffer(self):
        timestamp = int(time.time())
        # Create AudioSegment from the raw audio buffer
        audio_segment = AudioSegment(
            data=bytes(self.audio_buffer),
            sample_width=2,  # 16-bit PCM
            frame_rate=self.SAMPLE_RATE,
            channels=self.NUM_CHANNELS
        )

        # Trim leading and trailing silence
        trimmed_audio = self.trim_silence(audio_segment)

        if len(trimmed_audio) == 0:
            print("Trimmed audio is empty after removing silence.")
            self.audio_buffer = bytearray()
            self.is_recording = False
            self.silence_duration = 0
            return

        wav_filename = os.path.join(self.session_folder, f"output_{timestamp}.wav")
        # Export audio in the format expected by the recognizer (16 kHz, mono)
        trimmed_audio.set_frame_rate(16000).set_channels(1).export(wav_filename, format="wav")

        try:
            with sr.AudioFile(wav_filename) as source:
                # Adjust for ambient noise
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio_data = self.recognizer.record(source)
            # Get the recognition result with show_all=False to get a string directly
            text = self.recognizer.recognize_google(audio_data, language='en-ZA')
            print("Transcription:", text)
        except Exception as e:
            print(f"Transcription error: {e}")
            traceback.print_exc()
            text = f"[Error: {e}]"

        mp3_filename = os.path.join(self.session_folder, f"output_{timestamp}.mp3")
        trimmed_audio.export(mp3_filename, format="mp3")
        print(f"Audio saved as {mp3_filename}")

        with self.lock:
            recording = {
                'timestamp': timestamp,
                'wav_filename': wav_filename,
                'mp3_filename': mp3_filename,
                'text': text,  # Ensure text is a string
                'name': ''  # Initialize name as empty string
            }
            self.recordings.append(recording)
            self.save_recordings()
        self.audio_buffer = bytearray()
        self.is_recording = False
        self.silence_duration = 0

    def trim_silence(self, audio_segment, silence_thresh=-50, min_silence_len=100):
        """
        Trims leading and trailing silence from an audio segment.

        Parameters:
        - audio_segment: The AudioSegment to trim.
        - silence_thresh: Silence threshold in dBFS. Default is -50 dBFS.
        - min_silence_len: Minimum length of silence to detect (in ms). Default is 100 ms.

        Returns:
        - A new AudioSegment with silence trimmed from the start and end.
        """
        # Detect nonsilent parts [start, end] in milliseconds
        nonsilent_ranges = silence.detect_nonsilent(
            audio_segment,
            min_silence_len=min_silence_len,
            silence_thresh=silence_thresh
        )

        if not nonsilent_ranges:
            # The entire audio is silent
            return AudioSegment.empty()

        # Combine nonsilent parts
        start_trim = nonsilent_ranges[0][0]
        end_trim = nonsilent_ranges[-1][1]
        trimmed_audio = audio_segment[start_trim:end_trim]
        return trimmed_audio

    def get_status(self):
        with self.lock:
            return {
                'is_listening': self.is_listening,
                'is_recording': self.is_recording,
                'recordings': list(reversed(self.recordings)),  # Newest first
                'favorites': list(reversed(self.favorites))  # Newest first
            }

    def add_to_favorites(self, timestamp):
        # Find the recording in self.recordings
        with self.lock:
            recording = next((r for r in self.recordings if r['timestamp'] == timestamp), None)
            if not recording:
                return False
            # Check if already in favorites
            if any(fav['timestamp'] == timestamp for fav in self.favorites):
                print(f"Recording with timestamp {timestamp} is already in favorites.")
                return True  # Already in favorites
            # Copy the audio files to the favorites folder
            wav_dest = os.path.join(self.favorites_folder, os.path.basename(recording['wav_filename']))
            mp3_dest = os.path.join(self.favorites_folder, os.path.basename(recording['mp3_filename']))
            shutil.copy2(recording['wav_filename'], wav_dest)
            shutil.copy2(recording['mp3_filename'], mp3_dest)
            # Add to favorites list
            favorite = {
                'timestamp': recording['timestamp'],
                'wav_filename': wav_dest,
                'mp3_filename': mp3_dest,
                'text': recording['text'],
                'name': recording.get('name', '')
            }
            self.favorites.append(favorite)
            self.save_favorites()
        return True

    def save_favorites(self):
        print("Saving favorites...")
        favorites_data = []
        unique_timestamps = set()
        for fav in self.favorites:
            if fav['timestamp'] not in unique_timestamps:
                unique_timestamps.add(fav['timestamp'])
                favorites_data.append({
                    'timestamp': fav['timestamp'],
                    'wav_filename': os.path.basename(fav['wav_filename']),
                    'mp3_filename': os.path.basename(fav['mp3_filename']),
                    'text': fav.get('text', ''),
                    'name': fav.get('name', '')
                })
        favorites_json_path = os.path.join(self.favorites_folder, 'favorites.json')
        print(f"Saving favorites to {favorites_json_path}")
        try:
            with open(favorites_json_path, 'w') as f:
                json.dump(favorites_data, f)
            print("Favorites saved successfully.")
        except Exception as e:
            print(f"Error saving favorites: {e}")

    def load_favorites(self):
        favorites_json = os.path.join(self.favorites_folder, 'favorites.json')
        print(f"Loading favorites from {favorites_json}")
        if os.path.exists(favorites_json):
            try:
                with open(favorites_json, 'r') as f:
                    favorites_data = json.load(f)
                    for fav in favorites_data:
                        wav_filename = os.path.join(self.favorites_folder, fav['wav_filename'])
                        mp3_filename = os.path.join(self.favorites_folder, fav['mp3_filename'])
                        self.favorites.append({
                            'timestamp': fav['timestamp'],
                            'wav_filename': wav_filename,
                            'mp3_filename': mp3_filename,
                            'text': fav.get('text', ''),
                            'name': fav.get('name', '')
                        })
                print("Favorites loaded successfully.")
            except Exception as e:
                print(f"Error loading favorites: {e}")
                traceback.print_exc()
        else:
            # Create an empty favorites.json file
            print("Favorites JSON file does not exist. Creating a new one.")
            with open(favorites_json, 'w') as f:
                json.dump([], f)

        # Ensure all files in favorites folder are represented
        existing_timestamps = {fav['timestamp'] for fav in self.favorites}
        for filename in os.listdir(self.favorites_folder):
            if filename.endswith('.wav'):
                timestamp_str = filename.split('_')[1].split('.')[0]
                try:
                    timestamp = int(timestamp_str)
                except ValueError:
                    continue  # Skip files with unexpected names
                if timestamp not in existing_timestamps:
                    wav_filename = os.path.join(self.favorites_folder, filename)
                    mp3_filename = os.path.join(self.favorites_folder, f"output_{timestamp}.mp3")
                    self.favorites.append({
                        'timestamp': timestamp,
                        'wav_filename': wav_filename,
                        'mp3_filename': mp3_filename,
                        'text': '',
                        'name': ''
                    })
        # Remove duplicates
        self.favorites = list({fav['timestamp']: fav for fav in self.favorites}.values())
        # Sort favorites by timestamp (newest first)
        self.favorites.sort(key=lambda x: x['timestamp'], reverse=True)
        self.save_favorites()  # Save any new additions

    def save_recordings(self):
        print("Saving recordings...")
        recordings_data = []
        unique_timestamps = set()
        for rec in self.recordings:
            if rec['timestamp'] not in unique_timestamps:
                unique_timestamps.add(rec['timestamp'])
                recordings_data.append({
                    'timestamp': rec['timestamp'],
                    'wav_filename': os.path.basename(rec['wav_filename']),
                    'mp3_filename': os.path.basename(rec['mp3_filename']),
                    'text': rec.get('text', ''),
                    'name': rec.get('name', '')
                })
        recordings_json_path = os.path.join(self.session_folder, 'recordings.json')
        print(f"Saving recordings to {recordings_json_path}")
        try:
            with open(recordings_json_path, 'w') as f:
                json.dump(recordings_data, f)
            print("Recordings saved successfully.")
        except Exception as e:
            print(f"Error saving recordings: {e}")

    def load_recordings(self):
        recordings_json = os.path.join(self.session_folder, 'recordings.json')
        print(f"Loading recordings from {recordings_json}")
        if os.path.exists(recordings_json):
            try:
                with open(recordings_json, 'r') as f:
                    recordings_data = json.load(f)
                    for rec in recordings_data:
                        wav_filename = os.path.join(self.session_folder, rec['wav_filename'])
                        mp3_filename = os.path.join(self.session_folder, rec['mp3_filename'])
                        self.recordings.append({
                            'timestamp': rec['timestamp'],
                            'wav_filename': wav_filename,
                            'mp3_filename': mp3_filename,
                            'text': rec.get('text', ''),
                            'name': rec.get('name', '')
                        })
                print("Recordings loaded successfully.")
            except Exception as e:
                print(f"Error loading recordings: {e}")
                traceback.print_exc()
        else:
            # Create an empty recordings.json file
            print("Recordings JSON file does not exist. Creating a new one.")
            with open(recordings_json, 'w') as f:
                json.dump([], f)

        # Ensure all files in session folder are represented
        existing_timestamps = {rec['timestamp'] for rec in self.recordings}
        for filename in os.listdir(self.session_folder):
            if filename.endswith('.wav'):
                timestamp_str = filename.split('_')[1].split('.')[0]
                try:
                    timestamp = int(timestamp_str)
                except ValueError:
                    continue  # Skip files with unexpected names
                if timestamp not in existing_timestamps:
                    wav_filename = os.path.join(self.session_folder, filename)
                    mp3_filename = os.path.join(self.session_folder, f"output_{timestamp}.mp3")
                    self.recordings.append({
                        'timestamp': timestamp,
                        'wav_filename': wav_filename,
                        'mp3_filename': mp3_filename,
                        'text': '',
                        'name': ''
                    })
        # Remove duplicates
        self.recordings = list({rec['timestamp']: rec for rec in self.recordings}.values())
        # Sort recordings by timestamp (newest first)
        self.recordings.sort(key=lambda x: x['timestamp'], reverse=True)
        self.save_recordings()  # Save any new additions

    def update_name(self, list_type, timestamp, new_name):
        with self.lock:
            if list_type == 'recordings':
                recording = next((r for r in self.recordings if r['timestamp'] == timestamp), None)
                if recording:
                    recording['name'] = new_name
                    self.save_recordings()
                    print(f"Successfully updated name to '{new_name}' for recording with timestamp {timestamp}")
                    return True
                else:
                    print(f"Recording with timestamp {timestamp} not found in recordings.")
                    return False
            elif list_type == 'favorites':
                recording = next((r for r in self.favorites if r['timestamp'] == timestamp), None)
                if recording:
                    recording['name'] = new_name
                    self.save_favorites()
                    print(f"Successfully updated name to '{new_name}' for favorite with timestamp {timestamp}")
                    return True
                else:
                    print(f"Recording with timestamp {timestamp} not found in favorites.")
                    return False
            else:
                print(f"Invalid list_type '{list_type}' provided.")
                return False

# Flask app setup
app = Flask(__name__)

# Initialize the AudioRecorder
recorder = AudioRecorder()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/status')
def status():
    return jsonify(recorder.get_status())

@app.route('/play/<int:timestamp>', methods=['POST'])
def play_audio(timestamp):
    # Find the recording
    with recorder.lock:
        recording = next((r for r in recorder.recordings if r['timestamp'] == timestamp), None)
    if recording:
        threading.Thread(target=play_over_virtual_mic, args=(recording['wav_filename'],)).start()
        return jsonify({'status': 'playing', 'timestamp': timestamp})
    else:
        return jsonify({'status': 'error', 'message': 'Recording not found'}), 404

@app.route('/play_favorite/<int:timestamp>', methods=['POST'])
def play_favorite_audio(timestamp):
    # Find the recording in favorites
    with recorder.lock:
        recording = next((r for r in recorder.favorites if r['timestamp'] == timestamp), None)
    if recording:
        threading.Thread(target=play_over_virtual_mic, args=(recording['wav_filename'],)).start()
        return jsonify({'status': 'playing', 'timestamp': timestamp})
    else:
        return jsonify({'status': 'error', 'message': 'Favorite recording not found'}), 404

@app.route('/update_name/<list_type>/<int:timestamp>', methods=['POST'])
def update_name_route(list_type, timestamp):
    try:
        new_name = request.form.get('name', '')
        if not new_name:
            return jsonify({'status': 'error', 'message': 'Name is empty'}), 400
        print(f"Received request to update name to '{new_name}' for {list_type} with timestamp {timestamp}")
        success = recorder.update_name(list_type, timestamp, new_name)
        if success:
            print(f"Successfully updated name to '{new_name}' for {list_type} with timestamp {timestamp}")
            return jsonify({'status': 'success', 'timestamp': timestamp, 'name': new_name})
        else:
            print(f"Failed to update name for {list_type} with timestamp {timestamp}")
            return jsonify({'status': 'error', 'message': 'Recording not found'}), 404
    except Exception as e:
        print(f"Exception in update_name: {e}")
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500

def play_over_virtual_mic(filename):
    # Replace this with the name of your virtual microphone input device
    virtual_mic_name = 'CABLE Input (VB-Audio Virtual Cable)'  # Adjust as per your virtual mic's name

    # Get the virtual microphone as a speaker
    virtual_mic_speaker = None
    for speaker in sc.all_speakers():
        if virtual_mic_name.lower() in speaker.name.lower():
            virtual_mic_speaker = speaker
            break

    if virtual_mic_speaker is None:
        print("Virtual microphone not found.")
        return

    # Read the audio file
    audio_segment = AudioSegment.from_wav(filename)
    samples = np.array(audio_segment.get_array_of_samples()).astype(np.float32) / (1 << 15)
    samples = samples.reshape(-1, audio_segment.channels)
    # Play the samples to the virtual microphone
    with virtual_mic_speaker.player(samplerate=audio_segment.frame_rate, channels=audio_segment.channels, exclusive_mode=False) as player:
        player.play(samples)
    print(f"Played {filename} over virtual microphone.")

@app.route('/recordings/<filename>')
def get_recording(filename):
    # Ensure that the filename is safe
    if '..' in filename or filename.startswith('/'):
        abort(400)
    return send_from_directory(recorder.session_folder, filename)

@app.route('/favorites/<filename>')
def get_favorite(filename):
    # Ensure that the filename is safe
    if '..' in filename or filename.startswith('/'):
        abort(400)
    return send_from_directory(recorder.favorites_folder, filename)

@app.route('/favorite/<int:timestamp>', methods=['POST'])
def favorite_audio(timestamp):
    success = recorder.add_to_favorites(timestamp)
    if success:
        return jsonify({'status': 'success', 'timestamp': timestamp})
    else:
        return jsonify({'status': 'error', 'message': 'Recording not found'}), 404

if __name__ == '__main__':
    # Start the recorder only when running the script directly
    recorder.start()
    # Run the Flask app with debug mode enabled
    app.run(debug=True, use_reloader=False, host='0.0.0.0', port=5000)
