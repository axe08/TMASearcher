import os
import sys
import asyncio
import re
import psutil
import glob
from datetime import datetime
from pytube import YouTube, Playlist
import pandas as pd
from faster_whisper import WhisperModel
from numba import cuda
import requests
from bs4 import BeautifulSoup
import json
import spacy
import sqlite3
import asyncio


# Settings
use_spacy_for_sentence_splitting = 1
max_simultaneous_youtube_downloads = 4
disable_cuda_override = 1  # Set this to 1 to disable CUDA even if it is available
nlp = None  # Initialize nlp as None

# Helper functions

def query_episodes(start_date, end_date):
    conn = sqlite3.connect('TMASTL.db')
    cursor = conn.cursor()
    query = """
    SELECT URL
    FROM TMA
    WHERE Date BETWEEN ? AND ? AND transcribed_date IS NULL
    """
    cursor.execute(query, (start_date, end_date))
    episodes = cursor.fetchall()
    conn.close()
    print(f"Fetched {len(episodes)} episodes.")  # Add this line
    return episodes


def update_transcribed_date(url):
    conn = sqlite3.connect('TMASTL.db')
    cursor = conn.cursor()
    update_query = """
    UPDATE TMA
    SET transcribed_date = ?
    WHERE URL = ?
    """
    # Using datetime.now() to get the current date and time.
    cursor.execute(update_query, (datetime.now(), url))
    conn.commit()
    conn.close()

async def process_audio_file(url, title):
    mp3_url = extract_mp3_url_from_page(url)
    if mp3_url:
        audio_file_path = download_mp3(mp3_url, title)
        if audio_file_path:
            # Now the processing happens with the dynamically passed URL
            audio_file_size_mb = os.path.getsize(audio_file_path) / (1024 * 1024)
            combined_transcript_text, combined_transcript_text_list_of_metadata_dicts, list_of_transcript_sentences = await compute_transcript_with_whisper_from_audio_func(audio_file_path, title, audio_file_size_mb)
            # Continue with your processing...
            update_transcribed_date(url)  # Ensure this line is in the function to update the DB
    else:
        print(f"Failed to extract MP3 URL for {title}.")
        return True
    return False

async def process_episodes(start_date, end_date):
    episodes = query_episodes(start_date, end_date)
    for episode_tuple in episodes:
        url = episode_tuple[0]  # Directly access the URL, assuming it's the first element
        title = url.split('/')[-2]  # Derive the title from the URL
        print(f"Processing episode: {title}")
        await process_audio_file(url, title)


def load_spacy_model():
    global nlp  # Use the global nlp variable
    if use_spacy_for_sentence_splitting:
        print("Loading spaCy model...")
        model_name = "en_core_web_sm"
        try:
            nlp = spacy.load(model_name)  # Try to load the model
        except Exception as e:
            print(f"Error loading spaCy model {model_name}: {e}")
            # Optionally, handle downloading the model here if it's not found


def extract_mp3_url_from_page(url):
    # Specify headers with a User-Agent to mimic a browser request
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
    }
    # Make the request with the headers
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        soup = BeautifulSoup(response.content, 'html.parser')
        script_tags = soup.find_all('script')
        for script in script_tags:
            if 'var config_' in script.text:
                start = script.text.find('{')
                end = script.text.rfind('}') + 1
                json_str = script.text[start:end]
                try:
                    config = json.loads(json_str)
                    mp3_url = config['episode']['media']['mp3']
                    return mp3_url
                except json.JSONDecodeError as e:
                    print(f"Error decoding JSON from script tag: {e}")
    else:
        print(f"Failed to fetch page content. Status code: {response.status_code}")
    return None

def add_to_system_path(new_path):
    if new_path not in os.environ["PATH"].split(os.pathsep):  # Check if the new path already exists in PATH
        os.environ["PATH"] = new_path + os.pathsep + os.environ["PATH"]  # Add the new path to PATH
    if sys.platform == "win32" and ' ' in new_path and not new_path.startswith('"') and not new_path.endswith('"'):  # For Windows, wrap the path in quotes if it contains spaces and isn't already quoted
        os.environ["PATH"] = f'"{new_path}"' + os.pathsep + os.environ["PATH"]

def get_cuda_toolkit_path():
    home_dir = os.path.expanduser('~')  # Get the home directory of the current user
    if sys.platform in ["win32", "linux", "linux2", "darwin"]:  # Build the base path to the Anaconda 'pkgs' directory; Works for Windows, Linux, macOS
        anaconda_base_path = os.path.join(home_dir, "anaconda3", "pkgs")
    cuda_glob_pattern = os.path.join(anaconda_base_path, "cudatoolkit-*", "Library", "bin")  # Construct the glob pattern for the cudatoolkit directory
    cuda_paths = glob.glob(cuda_glob_pattern)  # Use glob to find directories that match the pattern
    if cuda_paths:  # Select the first matching path (assuming there is at least one match)
        return cuda_paths[0]  # Return the first matched path; This is the path to the cudatoolkit directory
    return None

def download_mp3(url, title):
    audio_dir = 'downloaded_audio'
    audio_filename = clean_filename(title) + '.mp3'
    audio_file_path = os.path.join(audio_dir, audio_filename)
    if not os.path.exists(audio_file_path):
        print(f"Downloading: {title}")
        response = requests.get(url, allow_redirects=True)
        with open(audio_file_path, 'wb') as file:
            file.write(response.content)
        print(f"Downloaded to: {audio_file_path}")
    else:
        print(f"File already exists: {audio_file_path}")
    return audio_file_path

def clean_filename(title):
    title = re.sub(r'[^\w\s-]', '', title)
    return re.sub(r'[-\s]+', '_', title).strip().lower()

def remove_pagination_breaks(text: str) -> str:
    text = re.sub(r'-(\n)(?=[a-z])', '', text)  # Remove hyphens at the end of lines when the word continues on the next line
    text = re.sub(r'(?<=\w)(?<![.?!-]|\d)\n(?![\nA-Z])', ' ', text)  # Replace line breaks that are not preceded by punctuation or list markers and not followed by an uppercase letter or another line break
    return text

def sophisticated_sentence_splitter(text):
    global nlp  # Ensure nlp is recognized within this function's scope
    text = remove_pagination_breaks(text)
    doc = nlp(text)
    sentences = [sent.text.strip() for sent in doc.sents]
    return sentences

async def download_audio(video):
    title = video.title
    mp3_url = extract_mp3_url_from_page(episode_page_url)
    if mp3_url:
        audio_file_path = download_mp3(mp3_url, title)
        if audio_file_path:
            return audio_file_path, clean_filename(title)
    else:
        print("Failed to extract MP3 URL from the webpage.")
    return None, None

async def compute_transcript_with_whisper_from_audio_func(audio_file_path, audio_file_name, audio_file_size_mb):
    cuda_toolkit_path = get_cuda_toolkit_path()
    if cuda_toolkit_path:
        add_to_system_path(cuda_toolkit_path)
    combined_transcript_text = ""
    combined_transcript_text_list_of_metadata_dicts = []
    list_of_transcript_sentences = []
    if cuda.is_available() and not disable_cuda_override:
        print("CUDA is available. Using GPU for transcription.")
        device = "cuda"
        compute_type = "float16"  # Use FP16 for faster computation on GPU
    else:
        print("CUDA not available. Using CPU for transcription.")
        device = "cpu"
        compute_type = "auto"  # Use default compute type for CPU
    model = WhisperModel("medium.en", device=device, compute_type=compute_type)
    request_time = datetime.utcnow()
    print(f"Computing transcript for {audio_file_name} which has a {audio_file_size_mb:.2f}MB file size...")
    segments, info = await asyncio.to_thread(model.transcribe, audio_file_path, beam_size=7, vad_filter=True)
    if not segments:
        print(f"No segments were returned for file {audio_file_name}.")
        return [], {}, "", [], request_time, datetime.utcnow(), 0, ""
    for segment in segments:
        print(f"Processing segment: [Start: {segment.start:.2f}s, End: {segment.end:.2f}s] for file {audio_file_name} with text: {segment.text} ")
        combined_transcript_text += segment.text + " "
        sentences = sophisticated_sentence_splitter(segment.text)
        list_of_transcript_sentences.extend(sentences)
        metadata = {
            "start": round(segment.start, 2),
            "end": round(segment.end, 2),
            "text": segment.text,
            "avg_logprob": round(segment.avg_logprob, 2)
        }
        combined_transcript_text_list_of_metadata_dicts.append(metadata)
    with open(f'generated_transcript_combined_texts/{audio_file_name}.txt', 'w') as file:
        file.write(combined_transcript_text)
    df = pd.DataFrame(combined_transcript_text_list_of_metadata_dicts)
    df.to_csv(f'generated_transcript_metadata_tables/{audio_file_name}.csv', index=False)
    df.to_json(f'generated_transcript_metadata_tables/{audio_file_name}.json', orient='records', indent=4)
    return combined_transcript_text, combined_transcript_text_list_of_metadata_dicts, list_of_transcript_sentences

def merge_transcript_segments_into_combined_text(segments):
    if not segments:
        return "", [], []
    min_logprob = min(segment['avg_logprob'] for segment in segments)
    max_logprob = max(segment['avg_logprob'] for segment in segments)
    combined_text = ""
    sentence_buffer = ""
    list_of_metadata_dicts = []
    list_of_sentences = []
    char_count = 0
    time_start = None
    time_end = None
    total_logprob = 0.0
    segment_count = 0
    for segment in segments:
        if time_start is None:
            time_start = segment['start']
        time_end = segment['end']
        total_logprob += segment['avg_logprob']
        segment_count += 1
        sentence_buffer += segment['text'] + " "
        sentences = sophisticated_sentence_splitter(sentence_buffer)
        for sentence in sentences:
            combined_text += sentence.strip() + " "
            list_of_sentences.append(sentence.strip())
            char_count += len(sentence.strip()) + 1  # +1 for the space
            avg_logprob = total_logprob / segment_count
            model_confidence_score = normalize_logprobs(avg_logprob, min_logprob, max_logprob)
            metadata = {
                'start_char_count': char_count - len(sentence.strip()) - 1,
                'end_char_count': char_count - 2,
                'time_start': time_start,
                'time_end': time_end,
                'model_confidence_score': model_confidence_score
            }
            list_of_metadata_dicts.append(metadata)
        if sentences:
            sentence_buffer = sentences.pop() if len(sentences) % 2 != 0 else ""
    return combined_text, list_of_metadata_dicts, list_of_sentences

def normalize_logprobs(avg_logprob, min_logprob, max_logprob):
    range_logprob = max_logprob - min_logprob
    return (avg_logprob - min_logprob) / range_logprob if range_logprob != 0 else 0.5

async def main():
    # Create necessary directories
    load_spacy_model()
    os.makedirs('downloaded_audio', exist_ok=True)
    os.makedirs('generated_transcript_combined_texts', exist_ok=True)
    os.makedirs('generated_transcript_metadata_tables', exist_ok=True)
    start_date = '2024-04-02'
    end_date = '2024-04-03'
    
    # Process all episodes fetched from the database for the given date range
    await process_episodes(start_date, end_date)

# Ensuring main is called correctly
if __name__ == "__main__":
    asyncio.run(main())