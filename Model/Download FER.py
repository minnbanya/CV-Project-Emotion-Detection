import kagglehub

# Specify the download path
custom_download_path = "/home/minnb/work/CV_Project/data/FER"

# Download the dataset to the specified path
path = kagglehub.dataset_download("msambare/fer2013", path=custom_download_path)

print("Path to dataset files:", path)
