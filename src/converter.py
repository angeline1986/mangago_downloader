"""
Conversion functionality for the Mangago Downloader.
Supports converting downloaded manga images to PDF and CBZ formats.
"""
import os
import zipfile
import re
from pathlib import Path
from typing import List, Optional

from .pdf.generator import generate_pdf_from_images
from .output_paths import chapter_cbz_path, chapter_pdf_path


def convert_to_pdf(
    chapter_dir: str,
    output_path: Optional[str] = None,
    delete_images: bool = False
) -> Optional[str]:
    """
    Convert chapter images to a high-quality PDF without re-encoding.
    """
    try:
        image_files = _get_image_files(chapter_dir)
        if not image_files:
            print(f"No images found in {chapter_dir}")
            return None
        
        image_files.sort()
        
        if not output_path:
            output_path = str(chapter_pdf_path(chapter_dir))

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        generate_pdf_from_images(image_files, output_path)
        
        if delete_images:
            for image_file in image_files:
                try:
                    os.remove(image_file)
                except OSError as e:
                    print(f"Warning: Failed to delete {image_file}: {e}")
        
        return output_path
    except Exception as e:
        print(f"Error converting to PDF: {e}")
        return None


def convert_to_cbz(
    chapter_dir: str,
    output_path: Optional[str] = None,
    delete_images: bool = False
) -> Optional[str]:
    """
    Convert chapter images to CBZ (Comic Book ZIP).
    """
    try:
        image_files = _get_image_files(chapter_dir)
        if not image_files:
            print(f"No images found in {chapter_dir}")
            return None
        
        image_files.sort()
        
        if not output_path:
            output_path = str(chapter_cbz_path(chapter_dir))

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for image_file in image_files:
                arcname = os.path.basename(image_file)
                zipf.write(image_file, arcname)
        
        if delete_images:
            for image_file in image_files:
                try:
                    os.remove(image_file)
                except OSError as e:
                    print(f"Warning: Failed to delete {image_file}: {e}")
        
        return output_path
    except Exception as e:
        print(f"Error converting to CBZ: {e}")
        return None


def convert_manga_chapters(
    manga_dir: str,
    format: str = "pdf",
    delete_images: bool = False
) -> List[str]:
    """
    Convert all chapters of a manga to the specified format.
    """
    created_files = []
    
    try:
        # Current layout:
        #   <manga>/IMG/<chapter>/page-NNN.ext
        #
        # Keep compatibility with legacy manga directories where chapter
        # folders lived directly below <manga>.
        image_root = os.path.join(manga_dir, "IMG")
        chapters_root = image_root if os.path.isdir(image_root) else manga_dir

        chapter_dirs = [
            os.path.join(chapters_root, item)
            for item in os.listdir(chapters_root)
            if os.path.isdir(os.path.join(chapters_root, item))
        ]
    except FileNotFoundError:
        print(f"Error: Manga directory not found at {manga_dir}")
        return []

    chapter_dirs.sort()
    
    for chapter_dir in chapter_dirs:
        try:
            if format.lower() == "pdf":
                output_file = convert_to_pdf(chapter_dir, delete_images=delete_images)
            elif format.lower() == "cbz":
                output_file = convert_to_cbz(chapter_dir, delete_images=delete_images)
            else:
                print(f"Unsupported format: {format}")
                continue
            
            if output_file:
                created_files.append(output_file)
                print(f"Converted {os.path.basename(chapter_dir)} to {os.path.basename(output_file)}")
        except Exception as e:
            print(f"Error converting {os.path.basename(chapter_dir)}: {e}")
    
    return created_files


def _get_image_files(directory: str) -> List[str]:
    """
    Get all image files in a directory, sorted numerically.
    """
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff'}
    image_files = []
    
    try:
        for filename in os.listdir(directory):
            if os.path.splitext(filename)[1].lower() in image_extensions:
                image_files.append(os.path.join(directory, filename))
    except FileNotFoundError:
        print(f"Directory not found: {directory}")

    # Natural numeric sort also supports the downloader's page-001.png naming.
    def natural_key(path: str):
        name = os.path.splitext(os.path.basename(path))[0]
        return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]

    image_files.sort(key=natural_key)
    
    return image_files
