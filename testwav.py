import os
import subprocess
import sys

def list_wav_files(directory):
    """List all .wav files in the directory."""
    if not os.path.exists(directory):
        print(f"Directory '{directory}' does not exist.")
        return []
    files = [f for f in os.listdir(directory) if f.lower().endswith('.wav')]
    return sorted(files)

def play_sound(file_path):
    """Play the WAV file using aplay."""
    try:
        result = subprocess.run(["aplay", file_path], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Playing: {file_path}")
        else:
            print(f"Error playing {file_path}: {result.stderr}")
    except FileNotFoundError:
        print("aplay not found. Please install alsa-utils: sudo apt install alsa-utils")
    except Exception as e:
        print(f"Error playing {file_path}: {e}")

def main():
    voices_dir = "voices/"
    
    wav_files = list_wav_files(voices_dir)
    if not wav_files:
        print(f"No .wav files found in '{voices_dir}'.")
        return
    
    print("Available WAV files:")
    for i, file in enumerate(wav_files, start=1):
        print(f"{i}. {file}")
    
    while True:
        try:
            choice = input("Enter the number of the file to play (or 'q' to quit): ").strip()
            if choice.lower() == 'q':
                break
            idx = int(choice) - 1
            if 0 <= idx < len(wav_files):
                file_path = os.path.join(voices_dir, wav_files[idx])
                play_sound(file_path)
            else:
                print("Invalid choice. Please enter a valid number.")
        except ValueError:
            print("Invalid input. Please enter a number or 'q'.")
        except KeyboardInterrupt:
            break
    
    print("Test completed.")

if __name__ == "__main__":
    main()
