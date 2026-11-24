#!/bin/sh
# A tiny ffmpeg: it reads the audio formats Codetta supports, measures loudness for ReplayGain
# (the ebur128 filter) and converts songs for music apps on mobile data (AAC, MP3 through LAME,
# Opus). No video, no network, so it's a few MB instead of the 80+ MB of a full build. The
# Dockerfile and the snap run this inside ffmpeg's source folder; LAME and Opus come from the
# system (lame-dev / opus-dev on Alpine, libmp3lame-dev / libopus-dev on Ubuntu).
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
  --enable-libmp3lame --enable-libopus \
  --enable-encoder=pcm_s16le,aac,libmp3lame,libopus \
  --enable-muxer=null,adts,mp3,ogg,opus
