import subprocess

def run_script(script_path):
    # Runs a script and captures its output
    try:
        result = subprocess.run(['python', script_path], text=True, capture_output=True, check=True)
        print(f"Script {script_path} executed successfully.")
        print("Output:", result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error running {script_path}: {e}")
        print("Error output:", e.stderr)

def main():
    # List of scripts to be run in sequence
    scripts = [
        'daily_scarp.py',
        'BalloonScrape.py',
        'TMShowScrape.py',
        ''
    ]

    # Run each script in the list
    for script in scripts:
        run_script(script)

if __name__ == "__main__":
    main()
