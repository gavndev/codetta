#!/bin/sh
# A tiny ffmpeg for ReplayGain: it only reads the audio formats Codetta supports and measures
# loudness (the ebur128 filter). No video, no network, no encoders beyond what "-f null" needs,
# so it's a few MB instead of the 80+ MB of a full build. The Dockerfile runs this inside
# ffmpeg's source folder.
set -e
./configure \
  --prefix=/usr/local --disable-everything --disable-autodetect --disable-doc --disable-debug \
  --disable-network --disable-ffplay --disable-ffprobe --disable-avdevice --disable-swscale \
  --disable-asm --enable-small --enable-static --disable-shared \
  --enable-swresample --enable-avfilter --enable-avformat --enable-avcodec \
  --enable-protocol=file,pipe \
  --enable-demuxer=flac,mp3,mov,ogg,wav,aiff,w64,wv,tta,asf,dsf,aac,ape,mpc,mpc8,iff \
  --enable-decoder=ape,mpc7,mpc8,dst,flac,mp3,mp3float,mp2,mp2float,aac,aac_latm,alac,vorbis,opus,wavpack,tta,wmav1,wmav2,wmapro,dsd_lsbf,dsd_msbf,dsd_lsbf_planar,dsd_msbf_planar,pcm_s16le,pcm_s16be,pcm_s24le,pcm_s24be,pcm_s32le,pcm_s32be,pcm_f32le,pcm_f32be,pcm_f64le,pcm_f64be,pcm_u8,pcm_s8 \
  --enable-parser=flac,mpegaudio,aac,vorbis,opus \
  --enable-filter=ebur128,aresample,aformat,anull \
  --enable-muxer=null --enable-encoder=pcm_s16le
