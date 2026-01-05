import streamlit as st
import os
import shutil
import tempfile
import requests
from typing import Literal
from PIL import Image, ImageOps

# page config --------------
if 'scraping_active' not in st.session_state:
    st.session_state['scraping_active'] = False
if 'results' not in st.session_state:
    st.session_state['results'] = None

# If active, we default to collapsed. If user opens it, they see disabled controls.
sidebar_state = "collapsed" if st.session_state['scraping_active'] else "expanded"

st.set_page_config(
    page_title="INaturalist Downloader", 
    layout="wide", 
    initial_sidebar_state=sidebar_state,
    page_icon="ASSETS/ICON.png"
)

st.title("INaturalist Dataset Scraper")

# Main fucking logic of the scraper --------------
class InaturalistScraper:
    def __init__(self, scientific_name: str = None, taxon_id: str = None, n: int = 50):
        '''
        Parameters
        ----------
        scientific_name : str, optional
            The scientific name of the species to search for.
        taxon_id : str, optional
            The INaturalist taxon ID of the species to search for.
        n : int, optional
            The number of images to download. Default is 50.       
        '''
        # Either scientific_name or taxon_id must be provided
        self.scientific_name = scientific_name
        self.taxon_id = taxon_id

        self.found_name = scientific_name if scientific_name else "Unknown"
        self.n = n

    def resolve_taxon(self):
        """
        If we have a name, get the ID. 
        If we have an ID, verify it and get the name.

        Returns
        -------
        success : bool
            Whether the resolution was successful.
        message : str
            Details about the resolution.
        """
        if self.taxon_id:
            # Get its actual found name
            url = f"https://api.inaturalist.org/v1/taxa/{self.taxon_id}"
            try:
                response = requests.get(url)
                response.raise_for_status()
                data = response.json()
                if data['results']:
                    self.found_name = data['results'][0]['name']
                    return True, f"Resolved ID {self.taxon_id} to '{self.found_name}'"
                else:
                    return False, "Taxon ID not found."
            except Exception as e:
                return False, str(e)

        elif self.scientific_name:
            # Get its id and actual name
            url = "https://api.inaturalist.org/v1/taxa"
            params = {'q': self.scientific_name, 'rank': 'species', 'per_page': 1}
            try:
                response = requests.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                if data['results']:
                    self.taxon_id = data['results'][0]['id']
                    self.found_name = data['results'][0]['name']
                    return True, f"Resolved '{self.scientific_name}' to ID {self.taxon_id}"
                else:
                    return False, f"Could not find taxon for '{self.scientific_name}'"
            except Exception as e:
                return False, str(e)

    def fetch_observation_pics(self, quality_grade: Literal["research", "all"] = "all"):
        '''
        Fetch observation pictures for the given taxon ID. 
        
        Parameters
        ------------
        - quality_grade: str
            The quality grade of observations to consider. Can be "research" or "all". Default is "all".
        ------------

        Returns
        ------------
        - observation_pics: List[str]
            A list of observation picture URLs.
        ------------
        '''
        observation_pics = set()
        page = 1
        observation_onePage = 200
        
        status_text = st.empty()
        prog_bar = st.progress(0)

        # Get observations until reaches self.n, one page gets you approx 200 obs or so.
        while True:
            status_text.caption(f"Page {page} | Found {len(observation_pics)}/{self.n}")

            url = "https://api.inaturalist.org/v1/observations"
            params = {
                'taxon_id': self.taxon_id,
                'per_page': observation_onePage,
                'page': page,
                'order': 'desc',
                'order_by': 'created_at',
                'ident_taxon_id': self.taxon_id,
                'quality_grade' : 'research' if quality_grade == "research" else "any"
                }
            try:
                response = requests.get(url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
                results = data.get('results', [])

                if not results:
                    # No more observations
                    break

                print(f"Fetched {len(results)} observations. from page {page}.")

                scraped_one_page = 0
                while len(observation_pics) < self.n and scraped_one_page < len(results):
                    photos = results[scraped_one_page].get('photos', [])
                    # one observation can have multiple photos
                    for photo in photos:
                        url = photo.get('url', '')
                        if url:
                            original_url = url.replace('square', 'original')
                            observation_pics.add(original_url)
                        if len(observation_pics) >= self.n:
                            break
                    scraped_one_page += 1
                
                # Break the main page loop if self.n is reached
                if len(observation_pics) >= self.n:
                    break
                
                # Ik it's impossible for page to exceed 1000 pages in this loop, but just in case. 
                if page > 1000:
                    break
                page += 1
                prog_bar.progress(min(len(observation_pics) / self.n, 1.0))

            except requests.exceptions.RequestException as e:
                st.error(f"API Error: {e}")
                break

        status_text.empty()
        prog_bar.empty()

        return list(observation_pics)

    def download_images(self, image_urls, save_dir=""):
        '''
        Download images from the provided URLs.
        
        Parameters
        ------------
        - image_urls: List[str]
            A list of image URLs to download.
        - save_dir: str
            The directory to save the downloaded images. If not provided, uses the scientific name as folder name.
        ---------
        '''
        if not os.path.exists(save_dir):
                    os.makedirs(save_dir)
                    
        downloaded_paths = []

        # Download Progress
        cols = st.columns([1, 4])
        # Text on left
        with cols[0]:
            status_text = st.empty()
            status_text.write("**Downloading... 0%**")
        # Progress bar on right
        with cols[1]:
            dl_bar = st.progress(0)

        total_images = len(image_urls)

        for i, url in enumerate(image_urls):
            try:
                filename = f"{i}_{self.found_name.replace(' ', '_')}.jpg"
                filepath = os.path.join(save_dir, filename)
                
                img_data = requests.get(url.replace("medium", "original"), timeout=5).content
                with open(filepath, 'wb') as handler:
                    handler.write(img_data)
                
                downloaded_paths.append(filepath)

                # Update Progress UI
                progress_fraction = (i + 1) / total_images
                percentage = int(progress_fraction * 100)
               
                dl_bar.progress(progress_fraction)
                status_text.write(f"**Downloading... {percentage}%**")

            except Exception as e:
                continue
        
        # Clea UI when done
        dl_bar.empty()
        status_text.write("**Download Complete!**")
        
        return downloaded_paths

# Sidebar Configuration --------------
st.sidebar.header("Configuration")

# if scraping is active, lock the controls
locked = st.session_state['scraping_active']
if locked:
    st.sidebar.info("**Scraping in progress...**\n\nControls are disabled until it's finished.")

# sidebar inputs
input_method = st.sidebar.radio(
    "Search Method", 
    ["Scientific Name", "Taxon ID"], 
    disabled=locked
)

# Gotta define these first, otherwise comiler will start bitching
sci_name_input = None
taxon_id_input = None

if input_method == "Scientific Name":
    sci_name_input = st.sidebar.text_input(
        "Scientific Name",
        disabled=locked
    )
else:
    taxon_id_input = st.sidebar.text_input(
        "Taxon ID", 
        disabled=locked
    )

num_images = st.sidebar.slider(
    "Number of Images", 
    min_value=0, 
    max_value=1000, 
    value=50,
    step=10,
    disabled=locked
)

quality_grade = st.sidebar.selectbox(
    "Quality Grade", 
    ["all", "research"], 
    index=0,    # default to "all" 
    disabled=locked
)

# divider
st.sidebar.markdown("---")

# sidebar start button
if not locked:
    if st.sidebar.button("Start Scraping", type="primary"):
        st.session_state['scraping_active'] = True
        st.rerun()
else:
    st.sidebar.button(" Scraping...", disabled=True)    # Button is once more disabled during active scraping


# File management & Scraping Logic --------------

if st.session_state['scraping_active']:
    
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Initialize Scraper
        scraper = InaturalistScraper(
            scientific_name=sci_name_input, 
            taxon_id=taxon_id_input, 
            n=num_images
        )

        # get the taxon ID / name        
        with st.spinner("Resolving Taxon..."):
            success, msg = scraper.resolve_taxon()
            
        if not success:
            st.error(msg)
            st.session_state['scraping_active'] = False 
        else:
            st.success(msg)
            
            # Get Image URLs
            st.subheader("1. Fetching Metadata")
            image_urls = scraper.fetch_observation_pics(quality_grade=quality_grade)
            
            if not image_urls:
                st.warning("No images found.")
                st.session_state['scraping_active'] = False
            else:
                # If no error shithead, proceed to download
                st.subheader("2. Downloading Images")
                saved_paths = scraper.download_images(image_urls, save_dir=temp_dir)

                # Zip and Save Results to Session State
                st.subheader("3. Finalizing")
                zip_name = f"{scraper.found_name.replace(' ', '_')}_dataset"
                zip_path_temp = shutil.make_archive(
                    os.path.join(tempfile.gettempdir(), zip_name), 
                    'zip', 
                    temp_dir
                )
                
                # Load zip into memory
                with open(zip_path_temp, "rb") as f:
                    zip_bytes = f.read()

                # Save to session state
                st.session_state['results'] = {
                    'paths': saved_paths,
                    'zip_bytes': zip_bytes,
                    'zip_name': f"{zip_name}.zip"
                }
                
                st.success("Scraping Completed!")
                st.session_state['scraping_active'] = False
                st.rerun()

    except Exception as e:
        st.error(f"An error occurred: {e}")
        st.session_state['scraping_active'] = False

# Results Display & Download --------------
if not st.session_state['scraping_active'] and st.session_state['results']:
    results = st.session_state['results']
    saved_paths = results['paths']
    
    st.divider()
    st.header("Scraping Complete")
    
    # Grid for Preview
    st.subheader("Preview (Max 8)")
    cols = st.columns(4)
    max_preview = min(len(saved_paths), 8)
    
    for i in range(max_preview):
        with cols[i % 4]:
            try:
                if os.path.exists(saved_paths[i]):
                    img = Image.open(saved_paths[i])
                    img_resized = ImageOps.fit(img, (300, 150), Image.Resampling.LANCZOS)
                    st.image(img_resized, caption=f"Img {i+1}")
            except:
                pass

    # Download Button
    st.subheader("Export")
    st.download_button(
        label="Download Dataset (.zip)",
        data=results['zip_bytes'],
        file_name=results['zip_name'],
        mime="application/zip",
        type="primary"
    )
    
    if st.button("Clear Results"):
        st.session_state['results'] = None
        st.rerun()