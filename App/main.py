import sys
import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstRtspServer", "1.0")
from gi.repository import Gst, GLib
import yaml
import argparse
import platform
import os
import pyds

# Set GST_DEBUG to 4 (debug level)
# os.environ['GST_DEBUG'] = '6'

# Initialize GStreamer
Gst.init(None)

cameras = []

# Input file or stream
with open('config/main_config.yaml') as yml_file:
    _ = yml_file.readline()
    config = yaml.safe_load(yml_file)
    
    num_cam = config['Main']['iCamNum']

    for i in range(num_cam):
        camera_tag = f"Cam{i + 1}"
        url = config[camera_tag]['sURI']
        cameras.append(url)
def is_aarch64():
    return platform.uname()[4] == 'aarch64'

# Function to probe inference metadata
def probe_inference_metadata(pad, info, user_data):
    # Get the buffer from the info
    buffer = info.get_buffer()
    if not buffer:
        print("Error: Could not get buffer from metadata.")
        return Gst.PadProbeReturn.OK

    # Extract the metadata attached to the buffer (user metadata)
    gst_buffer = info.get_buffer()
    if not gst_buffer:
        print("Unable to get GstBuffer ")
        return
    batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))

    if batch_meta:
        # Process metadata here (NvDsBatchMeta)
        # print("Found metadata in buffer.")
        # Access the metadata contained in the batch_meta
        # batch_meta = batch_meta.data  # This is where your batch metadata is stored
        l_frame = batch_meta.frame_meta_list
        while l_frame is not None:        
            try:
                frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
            except StopIteration:
                break
            # Process frame metadata, which holds detection results
            # print("Frame Metadata: ", frame_meta)

            # Access objects detected in the frame
            # object_meta = frame_meta.obj_meta_list
            l_obj = frame_meta.obj_meta_list
            if l_obj is None:
                print("NO DETECTIONS")
            while l_obj is not None:        
                try:
                    obj_meta = pyds.NvDsObjectMeta.cast(l_obj.data)
                except StopIteration:
                    break
                print(f"Object detected: Class ID {obj_meta.class_id}, Confidence: {obj_meta.confidence}")
                # You can also access bounding box information here
                print(f"Bounding Box: ({obj_meta.rect_params.left}, {obj_meta.rect_params.top}, "
                      f"{obj_meta.rect_params.width}, {obj_meta.rect_params.height})")

                try:
                    l_obj = l_obj.next
                except StopIteration:
                    break

            try:
                l_frame = l_frame.next
            except StopIteration:
                break
    else:
        print("Error: No metadata found in the buffer.")
        
    return Gst.PadProbeReturn.OK



def main(args):
    # Initialize GStreamer
    Gst.init(None)

    # Create the GStreamer pipeline
    pipeline = Gst.Pipeline.new("multi-source-pipeline")

    # Create the stream muxer
    streammux = Gst.ElementFactory.make("nvstreammux", "stream-muxer")
    streammux.set_property("batch-size", len(cameras))
    streammux.set_property("width", 1920)
    streammux.set_property("height", 1080)
    streammux.set_property("batched-push-timeout", 4000000)
    if not streammux:
        print("Error: Could not create 'nvstreammux' element.")
        sys.exit(1)
    pipeline.add(streammux)

    is_live = False
    # Add sources and link them to the muxer
    for i, uri in enumerate(cameras):
        is_live = add_decode_bin(i, args, pipeline, streammux, is_live)

    # Add the Primary Inference Engine (PGIE)
    pgie = Gst.ElementFactory.make("nvinfer", "primary-inference")
    pgie.set_property("config-file-path", "./config/pgie1_config.txt")
    pipeline.add(pgie)

    # Add the Secondary Inference Engine (SGIE)
    sgie = Gst.ElementFactory.make("nvinfer", "secondary-inference")
    sgie.set_property("config-file-path", "./config/sgie1_config.txt")
    pipeline.add(sgie)

    # Add the On-Screen Display (OSD)
    nvdsosd = Gst.ElementFactory.make("nvdsosd", "onscreendisplay")
    nvdsosd.set_property('process-mode',0)     # currently set to 0 which is cpu mode
    nvdsosd.set_property('display-text',1)     # Enable sets to display text
    pipeline.add(nvdsosd)

    # Add video convert and sink
    nvvidconv = Gst.ElementFactory.make("nvvideoconvert", "convertor")
    pipeline.add(nvvidconv)

    sink = Gst.ElementFactory.make("nveglglessink", "video-output")
    sink.set_property("sync", False)
    pipeline.add(sink)

    # Link the pipeline elements
    if not streammux.link(pgie):
        print("Error: Failed to link streammux to PGIE")
        sys.exit(1)

    if not pgie.link(sgie):
        print("Error: Failed to link PGIE to SGIE")
        sys.exit(1)

    if not sgie.link(nvdsosd):
        print("Error: Failed to link SGIE to OSD")
        sys.exit(1)

    if not nvdsosd.link(nvvidconv):
        print("Error: Failed to link OSD to video convertor")
        sys.exit(1)

    if not nvvidconv.link(sink):
        print("Error: Failed to link video convertor to sink")
        sys.exit(1)

    # Connect this probe to the metadata flow from `nvinfer` to `nvdsosd`
    pgie.get_static_pad('src').add_probe(Gst.PadProbeType.BUFFER, probe_inference_metadata, None)
    # Start the pipeline
    pipeline.set_state(Gst.State.PLAYING)

    # Create a main loop
    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        print("Pipeline interrupted")

    # Stop the pipeline
    pipeline.set_state(Gst.State.NULL)

def cb_newpad(decodebin, decoder_src_pad, data):
    print("In cb_newpad\n")
    caps = decoder_src_pad.get_current_caps()
    if not caps:
        caps = decoder_src_pad.query_caps()
    gststruct = caps.get_structure(0)
    gstname = gststruct.get_name()
    source_bin = data
    features = caps.get_features(0)

    # Need to check if the pad created by the decodebin is for video and not
    # audio.
    print("gstname=", gstname)
    if gstname.find("video") != -1:
        # Link the decodebin pad only if decodebin has picked nvidia
        # decoder plugin nvdec_*. We do this by checking if the pad caps contain
        # NVMM memory features.
        print("features=", features)
        if features.contains("memory:NVMM"):
            # Get the source bin ghost pad
            bin_ghost_pad = source_bin.get_static_pad("src")
            if not bin_ghost_pad.set_target(decoder_src_pad):
                sys.stderr.write(
                    "Failed to link decoder src pad to source bin ghost pad\n"
                )
        else:
            sys.stderr.write(" Error: Decodebin did not pick nvidia decoder plugin.\n")


def decodebin_child_added(child_proxy, Object, name, user_data):
    #with execution_lock:
    print("Decodebin child added:", name, "\n")
    if name.find("decodebin") != -1:
        Object.connect("child-added", decodebin_child_added, user_data)
    
    if not is_aarch64() and name.find("nvv4l2decoder") != -1:
        # Use CUDA unified memory in the pipeline so frames
        # can be easily accessed on CPU in Python.
        Object.set_property("cudadec-memtype", 2)

    
    if "source" in name:
        source_element = child_proxy.get_by_name("source")
        if source_element.find_property('drop-on-latency') != None:
            Object.set_property("drop-on-latency", True)

def create_source_bin(index, uri, is_live):
    print("Creating source bin")

    # Create a source GstBin to abstract this bin's content from the rest of the pipeline
    bin_name = "source-bin-%02d" % index
    print(bin_name)
    nbin = Gst.Bin.new(bin_name)
    if not nbin:
        sys.stderr.write(" Unable to create source bin \n")

    # Source element for reading from the uri.
    # We will use decodebin and let it figure out the container format of the
    # stream and the codec and plug the appropriate demux and decode plugins.
    # if file_loop:
    #     # use nvurisrcbin to enable file-loop
    #     uri_decode_bin=Gst.ElementFactory.make("nvurisrcbin", "uri-decode-bin")
    #     uri_decode_bin.set_property("file-loop", 1)
    #     uri_decode_bin.set_property("cudadec-memtype", 2)
    uri_decode_bin=Gst.ElementFactory.make("nvurisrcbin", "uri-decode-bin")
    uri_decode_bin.set_property("cudadec-memtype", 2)
    uri_decode_bin.set_property("rtsp-reconnect-interval", 10)
        # uri_decode_bin = Gst.ElementFactory.make("uridecodebin", "uri-decode-bin")
    uri_decode_bin.set_property("select-rtp-protocol", 0)
        
    if not uri_decode_bin:
        sys.stderr.write(" Unable to create uri decode bin \n")
    
    if is_live:
        uri_decode_bin.set_property("type", 4)
    # We set the input uri to the source element
    uri_decode_bin.set_property("uri", uri)
    # Connect to the "pad-added" signal of the decodebin which generates a
    # callback once a new pad for raw data has beed created by the decodebin
    uri_decode_bin.connect("pad-added", cb_newpad, nbin)
    uri_decode_bin.connect("child-added", decodebin_child_added, nbin)

    # We need to create a ghost pad for the source bin which will act as a proxy
    # for the video decoder src pad. The ghost pad will not have a target right
    # now. Once the decode bin creates the video decoder and generates the
    # cb_newpad callback, we will set the ghost pad target to the video decoder src pad.

    Gst.Bin.add(nbin, uri_decode_bin)
    bin_pad = nbin.add_pad(Gst.GhostPad.new_no_target("src", Gst.PadDirection.SRC))
    if not bin_pad:
        sys.stderr.write(" Failed to add ghost pad in source bin \n")
        return None
    return nbin

def add_decode_bin(src, args, pipeline, streammux, is_live):
    print("Creating source_bin ", src, " \n ")
    uri_name = args[src]
    if uri_name.find("rtsp://") == 0:
        is_live = True
    print(uri_name)
    source_bin = create_source_bin(src, uri_name, is_live)
    if not source_bin:
        sys.stderr.write("Unable to create source bin \n")
    pipeline.add(source_bin)
    #g_source_bin_list[i] = source_bin
    padname = 'sink_%u' % src
    sinkpad = streammux.get_request_pad(padname)
    if not sinkpad:
        sys.stderr.write("Unable to create sink pad bin \n")
    srcpad = source_bin.get_static_pad("src")
    if not srcpad:
        sys.stderr.write("Unable to create src pad bin \n")
    srcpad.link(sinkpad)
    if is_live:
        print("At least one of the sources is live")
        streammux.set_property('live-source', 1)
    return is_live

def parse_args():
    parser = argparse.ArgumentParser(description="RTSP Output Sample Application Help ")
    parser.add_argument(
        "-c",
        "--codec",
        default="H264",
        help="RTSP Streaming Codec H264/H265 , default=H264",
        choices=["H264", "H265"],
    )
    parser.add_argument(
        "-b", "--bitrate", default=6000000, help="Set the encoding bitrate ", type=int
    )
    args = parser.parse_args()
    global codec
    global bitrate
    codec = args.codec
    bitrate = args.bitrate
    return True

if __name__ == "__main__":
    parse_args()
    sys.exit(main(cameras))
