from __future__ import division

import math

from . import base as gp
from .utils import clamp


class GP3File(gp.GPFileBase):

    """A reader for GuitarPro 3 files."""

    _supportedVersions = ['FICHIER GUITAR PRO v3.00']
    _tripletFeel = gp.TripletFeel.none

    def __init__(self, *args, **kwargs):
        super(GP3File, self).__init__(*args, **kwargs)

    # Reading
    # =======

    def readSong(self):
        """Read the song.

        A song consists of score information, triplet feel, tempo, song
        key, MIDI channels, measure and track count, measure headers,
        tracks, measure.

        -   Score information.
            See :meth:`readInfo`.

        -   Triplet feel: :ref:`bool`.
            If value is true, then triplet feel is set to eigth.

        -   Tempo: :ref:`int`.

        -   Key: :ref:`int`.
            Key signature of the song.

        -   MIDI channels: list of :class:`guitarpro.base.MidiChannel`.
            See :meth:`readMidiChannels`.

        -   Number of measures: :ref:`int`.

        -   Number of tracks: :ref:`int`.

        -   Measure headers: list of :class:`guitarpro.base.MeasureHeader`.
            See :meth:`readMeasureHeaders`.

        -   Tracks: list of :class:`guitarpro.base.Track`.
            See :meth:`readTracks`.

        -   Measures: table of :class:`guitarpro.base.Measure`.
            See :meth:`readMeasures`.

        """
        if not self.readVersion():
            raise gp.GPException("unsupported version '%s'" %
                                 self.version)
        song = gp.Song()
        self.readInfo(song)
        self._tripletFeel = (gp.TripletFeel.eighth if self.readBool()
                             else gp.TripletFeel.none)
        song.tempo = self.readInt()
        song.key = gp.KeySignature((self.readInt(), 0))
        channels = self.readMidiChannels()
        measureCount = self.readInt()
        trackCount = self.readInt()
        self.readMeasureHeaders(song, measureCount)
        self.readTracks(song, trackCount, channels)
        self.readMeasures(song)
        return song

    def readInfo(self, song):
        """Read score information.

        Score information consists of sequence of :ref:`IntByteSizeStrings <int-byte-size-string>`:

        -   title
        -   subtitle
        -   artist
        -   album
        -   words
        -   copyright
        -   tabbed by
        -   instructions

        The sequence if followed by notice.
        Notice starts with the number of notice lines stored in :ref:`int`.
        Each line is encoded in :ref:`int-byte-size-string`.

        """
        song.title = self.readIntByteSizeString()
        song.subtitle = self.readIntByteSizeString()
        song.artist = self.readIntByteSizeString()
        song.album = self.readIntByteSizeString()
        song.words = self.readIntByteSizeString()
        song.music = song.words
        song.copyright = self.readIntByteSizeString()
        song.tab = self.readIntByteSizeString()
        song.instructions = self.readIntByteSizeString()
        notesCount = self.readInt()
        song.notice = []
        for __ in range(notesCount):
            song.notice.append(self.readIntByteSizeString())

    def readMidiChannels(self):
        """Read MIDI channels.

        Guitar Pro format provides 64 channels (4 MIDI ports by 16 channels), the channels are stored in this order:

        -   port1/channel1
        -   port1/channel2
        -   ...
        -   port1/channel16
        -   port2/channel1
        -   ...
        -   port4/channel16

        Each channel has the following form:

        -   Instrument: :ref:`int`.

        -   Volume: :ref:`byte`.

        -   Balance: :ref:`byte`.

        -   Chorus: :ref:`byte`.

        -   Reverb: :ref:`byte`.

        -   Phaser: :ref:`byte`.

        -   Tremolo: :ref:`byte`.

        -   blank1: :ref:`byte`.

        -   blank2: :ref:`byte`.

        """
        channels = []
        for i in range(64):
            newChannel = gp.MidiChannel()
            newChannel.channel = i
            newChannel.effectChannel = i
            instrument = self.readInt()
            if newChannel.isPercussionChannel and instrument == -1:
                instrument = 0
            newChannel.instrument = instrument
            newChannel.volume = self.toChannelShort(self.readSignedByte())
            newChannel.balance = self.toChannelShort(self.readSignedByte())
            newChannel.chorus = self.toChannelShort(self.readSignedByte())
            newChannel.reverb = self.toChannelShort(self.readSignedByte())
            newChannel.phaser = self.toChannelShort(self.readSignedByte())
            newChannel.tremolo = self.toChannelShort(self.readSignedByte())
            channels.append(newChannel)
            # Backward compatibility with version 3.0
            self.skip(2)
        return channels

    def toChannelShort(self, data):
        value = max(-32768, min(32767, (data << 3) - 1))
        return max(value, -1) + 1

    def readMeasureHeaders(self, song, measureCount):
        """Read measure headers.

        The *measures* are written one after another, their number have been specified previously.

        :param measureCount: number of measures to expect.

        """
        previous = None
        for number in range(1, measureCount + 1):
            header = self.readMeasureHeader(number, song, previous)
            song.addMeasureHeader(header)
            previous = header

    def readMeasureHeader(self, number, song, previous=None):
        """Read measure header.

        The first byte is the measure's flags.
        It lists the data given in the current measure.

        -   *0x01*: numerator of the key signature
        -   *0x02*: denominator of the key signature
        -   *0x04*: beginning of repeat
        -   *0x08*: end of repeat
        -   *0x10*: number of alternate ending
        -   *0x20*: presence of a marker
        -   *0x40*: tonality of the measure
        -   *0x80*: presence of a double bar

        Each of these elements is present only if the corresponding bit is a 1.

        The different elements are written (if they are present) from lowest to highest bit.

        Exceptions are made for the double bar and the beginning of repeat whose sole presence is enough, complementary data is not necessary.

        -   Numerator of the key signature: :ref:`byte`.

        -   Denominator of the key signature: :ref:`byte`.

        -   End of repeat: :ref:`byte`.
            Number of repeats until the previous beginning of repeat.

        -   Number of alternate ending: :ref:`byte`.
            The number of alternate ending.

        -   Marker: see :meth:`GP3File.readMarker`.

        -   Tonality of the measure: 2 :ref:`Bytes <byte>`.
            These values encode a key signature change on the current piece.
            First byte is key signature root, second is key signature type.

        """
        flags = self.readByte()
        header = gp.MeasureHeader()
        header.number = number
        header.start = 0
        header.tempo.value = song.tempo
        header.tripletFeel = self._tripletFeel
        if flags & 0x01:
            header.timeSignature.numerator = self.readSignedByte()
        else:
            header.timeSignature.numerator = previous.timeSignature.numerator
        if flags & 0x02:
            header.timeSignature.denominator.value = self.readSignedByte()
        else:
            header.timeSignature.denominator.value = previous.timeSignature.denominator.value
        header.isRepeatOpen = bool(flags & 0x04)
        if flags & 0x08:
            header.repeatClose = self.readSignedByte()
        if flags & 0x10:
            header.repeatAlternative = self.readRepeatAlternative(song.measureHeaders)
        if flags & 0x20:
            header.marker = self.readMarker(header)
        if flags & 0x40:
            root = self.readSignedByte()
            type_ = self.readSignedByte()
            header.keySignature = gp.KeySignature((root, type_))
            header.keySignaturePresence = True
        elif header.number > 1:
            header.keySignature = previous.keySignature
        header.hasDoubleBar = bool(flags & 0x80)
        return header

    def readRepeatAlternative(self, measureHeaders):
        value = self.readByte()
        existingAlternatives = 0
        for header in reversed(measureHeaders):
            if header.isRepeatOpen:
                break
            existingAlternatives |= header.repeatAlternative
        return (1 << value) - 1 ^ existingAlternatives

    def readMarker(self, header):
        """Read marker.

        The markers are written in two steps. First is written an
        integer equal to the marker's name length + 1, then a string
        containing the marker's name. Finally the marker's color is
        written.

        """
        marker = gp.Marker()
        marker.measureHeader = header
        marker.title = self.readIntByteSizeString()
        marker.color = self.readColor()
        return marker

    def readColor(self):
        """Read color.

        Colors are used by :class:`guitarpro.base.Marker` and :class:`guitarpro.base.Track`.
        They consist of 3 consecutive bytes and one blank byte.

        """
        r = self.readByte()
        g = self.readByte()
        b = self.readByte()
        self.skip(1)
        return gp.Color(r, g, b)

    def readTracks(self, song, trackCount, channels):
        """Read tracks.

        The tracks are written one after another, their number having been specified previously in :meth:`GP3File.readSong`.

        :param trackCount: number of tracks to expect.

        """
        for i in range(trackCount):
            song.addTrack(self.readTrack(i + 1, channels))

    def readTrack(self, number, channels):
        """Read track.

        :param number: 1-based number of track.
        :param channels: list of :class:`guitarpro.base.MidiChannel` instances.

        The first byte is the track's flags.
        It presides the track's attributes:

        -   *0x01*: drums track
        -   *0x02*: 12 stringed guitar track
        -   *0x04*: banjo track
        -   *0x08*: blank bit
        -   *0x10*: blank bit
        -   *0x20*: blank bit
        -   *0x40*: blank bit
        -   *0x80*: blank bit

        Flags are followed by:

        -   Name: `String`.
            A 40 characters long string containing the track's name.

        -   Number of strings: :ref:`int`.
            An integer equal to the number of strings of the track.

        -   Tuning of the strings: `Table of integers`.
            The tuning of the strings is stored as a 7-integers table, the "Number of strings" first integers being really used. The strings are stored from the highest to the lowest.

        -   Port: :ref:`int`.
            The number of the MIDI port used.

        -   Channel: :class:`guitarpro.base.MidiChannel`. See :meth:`GP3File.readChannel`.

        -   Number of frets: :ref:`int`.
            The number of frets of the instrument.

        -   Height of the capo: :ref:`int`.
            The number of the fret on which a capo is set.
            If no capo is used, the value is 0.

        -   Track's color: :class:`guitarpro.base.Color`.
            The track's displayed color in Guitar Pro.

        """
        flags = self.readByte()
        track = gp.Track()
        track.isPercussionTrack = bool(flags & 0x01)
        track.is12StringedGuitarTrack = bool(flags & 0x02)
        track.isBanjoTrack = bool(flags & 0x04)
        track.number = number
        track.name = self.readByteSizeString(40)
        stringCount = self.readInt()
        for i in range(7):
            iTuning = self.readInt()
            if stringCount > i:
                oString = gp.GuitarString()
                oString.number = i + 1
                oString.value = iTuning
                track.strings.append(oString)
        track.port = self.readInt()
        self.readChannel(track, channels)
        if track.channel.channel == 9:
            track.isPercussionTrack = True
        track.fretCount = self.readInt()
        track.offset = self.readInt()
        track.color = self.readColor()
        return track

    def readChannel(self, track, channels):
        """Read MIDI channel.

        MIDI channel in Guitar Pro is represented by two integers.
        First is zero-based number of channel, second is zero-based number of channel used for effects.

        """
        index = self.readInt() - 1
        effectChannel = self.readInt() - 1
        if 0 <= index < len(channels):
            track.channel = channels[index]
            if track.channel.instrument < 0:
                track.channel.instrument = 0
            if not track.channel.isPercussionChannel:
                track.channel.effectChannel = effectChannel

    def readMeasures(self, song):
        """Read measures.

        Measures are written in the following order:

        -   measure 1/track 1
        -   measure 1/track 2
        -   ...
        -   measure 1/track m
        -   measure 2/track 1
        -   ...
        -   measure 2/track m
        -   ...
        -   measure n/track 1
        -   measure n/track 2
        -   ...
        -   measure n/track m

        """
        tempo = gp.Tempo(song.tempo)
        start = gp.Duration.quarterTime
        for header in song.measureHeaders:
            header.start = start
            for track in song.tracks:
                measure = gp.Measure(header)
                tempo = header.tempo
                track.addMeasure(measure)
                self.readMeasure(measure, track)
            header.tempo = tempo
            start += header.length

    def readMeasure(self, measure, track):
        """Read measure.

        The measure is written as number of beats followed by sequence
        of beats.

        """
        start = measure.start
        beats = self.readInt()
        for beat in range(beats):
            start += self.readBeat(start, measure, track, 0)

    def readBeat(self, start, measure, track, voiceIndex):
        """Read beat.

        The first byte is the beat flags.
        It lists the data present in the current beat:

        -   *0x01*: dotted notes
        -   *0x02*: presence of a chord diagram
        -   *0x04*: presence of a text
        -   *0x08*: presence of effects
        -   *0x10*: presence of a mix table change event
        -   *0x20*: the beat is a n-tuplet
        -   *0x40*: status: True if the beat is empty of if it is a rest
        -   *0x80*: blank bit

        Flags are followed by:

        -   Status: :ref:`byte`.
            If flag at *0x40* is true, read one byte.
            If value of the byte is ``0x00`` then beat is empty, if value is ``0x02`` then the beat is rest.

        -   Beat duration: :ref:`byte`.
            See :meth:`readDuration`.

        -   Chord diagram: :class:`guitarpro.base.Chord`.
            See :meth:`readChord`.

        -   Text: :class:`guitarpro.base.Text`.
            See :meth:`readText`.

        -   Beat effects: :class:`guitarpro.base.BeatEffects`.
            See :meth:`readBeatEffects`.

        -   Mix table change effect: :class:`guitarpro.base.MixTableChange`.
            See :meth:`readMixTableChange`.

        """
        flags = self.readByte()
        beat = self.getBeat(measure, start)
        voice = beat.voices[voiceIndex]
        if flags & 0x40:
            beatType = self.readByte()
            voice.isEmpty = (beatType & 0x02) == 0
        duration = self.readDuration(flags)
        effect = gp.NoteEffect()
        if flags & 0x02:
            self.readChord(len(track.strings), beat)
        if flags & 0x04:
            self.readText(beat)
        if flags & 0x08:
            self.readBeatEffects(beat, effect)
        if flags & 0x10:
            mixTableChange = self.readMixTableChange(measure)
            beat.effect.mixTableChange = mixTableChange
        self.readNotes(track, voice, duration, effect)
        return duration.time if not voice.isEmpty else 0

    def getBeat(self, measure, start):
        """Get beat from measure by start time."""
        for beat in measure.beats:
            if beat.start == start:
                return beat
        newBeat = gp.Beat()
        newBeat.start = start
        measure.addBeat(newBeat)
        return newBeat

    def readDuration(self, flags):
        """Read beat duration.

        Duration is composed of byte signifying duration and an integer that maps to :class:`guitarpro.base.Tuplet`.

        The byte maps to following values:

        -   *-2*: whole note
        -   *-1*: half note
        -    *0*: quarter note
        -    *1*: eighth note
        -    *2*: sixteenth note
        -    *3*: thirty-second note

        If flag at *0x20* is true, the tuplet is read.

        """
        duration = gp.Duration()
        duration.value = 1 << (self.readSignedByte() + 2)
        duration.isDotted = bool(flags & 0x01)
        if flags & 0x20:
            iTuplet = self.readInt()
            if iTuplet == 3:
                duration.tuplet.enters = 3
                duration.tuplet.times = 2
            elif iTuplet == 5:
                duration.tuplet.enters = 5
                duration.tuplet.times = 4
            elif iTuplet == 6:
                duration.tuplet.enters = 6
                duration.tuplet.times = 4
            elif iTuplet == 7:
                duration.tuplet.enters = 7
                duration.tuplet.times = 4
            elif iTuplet == 9:
                duration.tuplet.enters = 9
                duration.tuplet.times = 8
            elif iTuplet == 10:
                duration.tuplet.enters = 10
                duration.tuplet.times = 8
            elif iTuplet == 11:
                duration.tuplet.enters = 11
                duration.tuplet.times = 8
            elif iTuplet == 12:
                duration.tuplet.enters = 12
                duration.tuplet.times = 8
        return duration

    def readChord(self, stringCount, beat):
        """Read chord diagram.

        First byte is chord header. If it's set to 0, then following chord is written in default format.
        In this case chord diagram is decoded as:

        -   Name: :ref:`int-byte-size-string`.
            Name of the chord, e.g. *Em*.

        -   First fret: :ref:`int`.
            The fret from which the chord is displayed in chord editor.

        -   List of frets: 6 :ref:`Ints <int>`.
            Frets are listed in order: fret on the string 1, fret on the string 2, ..., fret on the string 6.
            If string is untouched then the values of fret is ``-1``.

        If chord header is set to 1, then chord diagram in encoded in more advanced format:

        -   Sharp: :ref:`bool`.
            If true, display all semitones as sharps, otherwise display as flats.

        -   Blank space, 3 :ref:`Bytes <byte>`.

        -   Root: :ref:`int`.
            Values are:

            *   -1 for customized chords
            *    0: C
            *    1: C#
            *   ...

        -   Type: :ref:`int`.
            Determines the chord type as followed.
            See :class:`guitarpro.base.ChordType` for mapping.

        -   Chord extension: :ref:`int`.
            See :class:`guitarpro.base.ChordExtension` for mapping.

        -   Bass note: :ref:`int`.
            Lowest note of chord as in *C/A*.

        -   Tonality: :ref:`int`.
            See :class:`guitarpro.base.ChordTonality` for mapping.

        -   Add: :ref:`bool`.
            Determines if a "add" (added note) is present in the chord.

        -   Name: :ref:`byte-size-string`.
            Max length is 22.

        -   Fifth tonality: :ref:`int`.
            Maps to :class:`guitarpro.base.ChordExtension`.

        -   Ninth tonality: :ref:`int`.
            Maps to :class:`guitarpro.base.ChordExtension`.

        -   Eleventh tonality: :ref:`int`.
            Maps to :class:`guitarpro.base.ChordExtension`.

        -   List of frets: 6 :ref:`Ints <int>`.
            Fret values are saved as in default format.

        -   Count of barres: :ref:`int`.
            Maximum count is 2.

        -   Barre frets: 2 :ref:`Ints <int>`.

        -   Barre start strings: 2 :ref:`Ints <int>`.

        -   Barre end string: 2 :ref:`Ints <int>`.

        -   Omissions: 7 :ref:`Bools <bool>`.
            If the value is true then note is played in chord.

        -   Blank space, 1 :ref:`byte`.

        """
        chord = gp.Chord(stringCount)
        newFormat = self.readBool()
        if not newFormat:
            self.readOldChord(chord)
        else:
            self.readNewChord(chord)
        if len(chord.notes) > 0:
            beat.setChord(chord)

    def readOldChord(self, chord):
        chord.name = self.readIntByteSizeString()
        chord.firstFret = self.readInt()
        if chord.firstFret:
            for i in range(6):
                fret = self.readInt()
                if i < len(chord.strings):
                    chord.strings[i] = fret

    def readNewChord(self, chord):
        chord.sharp = self.readBool()
        intonation = 'sharp' if chord.sharp else 'flat'
        self.skip(3)
        chord.root = gp.PitchClass(self.readInt(), intonation=intonation)
        chord.type = gp.ChordType(self.readInt())
        chord.extension = gp.ChordExtension(self.readInt())
        chord.bass = gp.PitchClass(self.readInt(), intonation=intonation)
        chord.tonality = gp.ChordTonality(self.readInt())
        chord.add = self.readBool()
        chord.name = self.readByteSizeString(22)
        chord.fifth = gp.ChordTonality(self.readInt())
        chord.ninth = gp.ChordTonality(self.readInt())
        chord.eleventh = gp.ChordTonality(self.readInt())
        chord.firstFret = self.readInt()
        for i in range(6):
            fret = self.readInt()
            if i < len(chord.strings):
                chord.strings[i] = fret
        chord.barres = []
        barresCount = self.readInt()
        barreFrets = self.readInt(2)
        barreStarts = self.readInt(2)
        barreEnds = self.readInt(2)
        for fret, start, end, __ in zip(barreFrets, barreStarts, barreEnds,
                                        range(barresCount)):
            barre = gp.Barre(fret, start, end)
            chord.barres.append(barre)
        chord.omissions = self.readBool(7)
        self.skip(1)

    def readText(self, beat):
        """Read beat text.

        Text is stored in :ref:`int-byte-size-string`.

        """
        text = gp.BeatText()
        text.value = self.readIntByteSizeString()
        beat.setText(text)

    def readBeatEffects(self, beat, effect):
        """Read beat effects.

        The first byte is effects flags:

        -   *0x01*: vibrato
        -   *0x02*: wide vibrato
        -   *0x04*: natural harmonic
        -   *0x08*: artificial harmonic
        -   *0x10*: fade in
        -   *0x20*: tremolo bar or slap
        -   *0x40*: stroke direction
        -   *0x80*: blank bit

        If flag at *0x20* is set, then beat effect has either tremolo bar or slap.
        Read the value of next byte, if it's 0 then tremolo bar should be read (see :meth:`readTremoloBar`).
        Else it's tapping and values of the byte map to:

        -   *1*: tap
        -   *2*: slap
        -   *3*: pop

        If flag at *0x40* is set, then stroke effect is expected.
        It consists of two :ref:`Bytes <byte>` which correspond to stroke up and stroke down.
        If value is greater than zero, the speed of stroke is determined, see :meth:`toStrokeValue`.

        """
        flags1 = self.readByte()
        effect.vibrato = bool(flags1 & 0x01) or effect.vibrato
        beat.effect.vibrato = bool(flags1 & 0x02) or beat.effect.vibrato
        beat.effect.fadeIn = bool(flags1 & 0x10)
        if flags1 & 0x20:
            flags2 = self.readByte()
            beat.effect.slapEffect = gp.SlapEffect(flags2)
            if beat.effect.slapEffect == gp.SlapEffect.none:
                self.readTremoloBar(beat.effect)
            else:
                self.readInt()
        if flags1 & 0x40:
            self.readBeatStroke(beat.effect)
        if flags1 & 0x04:
            harmonic = gp.NaturalHarmonic()
            effect.harmonic = harmonic
        if flags1 & 0x08:
            harmonic = gp.ArtificialHarmonic()
            effect.harmonic = harmonic

    def readTremoloBar(self, effect):
        """Read tremolo bar beat effect.

        The only type of tremolo bar effect Guitar Pro 3 supports is :attr:`dip <guitarpro.base.BendType.dip>`.
        The value of the effect is encoded in :ref:`Int` and shows how deep tremolo bar is pressed.

        """
        barEffect = gp.BendEffect()
        barEffect.type = gp.BendType.dip
        barEffect.value = self.readInt()
        barEffect.points.append(gp.BendPoint(0, 0))
        barEffect.points.append(
            gp.BendPoint(round(gp.BendEffect.maxPosition / 2),
                         round(-barEffect.value / (self.bendSemitone * 2))))
        barEffect.points.append(gp.BendPoint(gp.BendEffect.maxPosition, 0))
        effect.tremoloBar = barEffect

    def readBeatStroke(self, beatEffect):
        strokeUp = self.readSignedByte()
        strokeDown = self.readSignedByte()
        if strokeUp > 0:
            beatEffect.stroke.direction = gp.BeatStrokeDirection.up
            beatEffect.stroke.value = self.toStrokeValue(strokeUp)
        elif strokeDown > 0:
            beatEffect.stroke.direction = gp.BeatStrokeDirection.down
            beatEffect.stroke.value = self.toStrokeValue(strokeDown)

    def toStrokeValue(self, value):
        """Unpack stroke value.

        Stroke value maps to:

        -   *1*: `sixty fourth <guitarpro.base.Duration.sixtyFourth>`_
        -   *2*: `sixty fourth <guitarpro.base.Duration.sixtyFourth>`_
        -   *3*: `thirty second <guitarpro.base.Duration.thirtySecond>`_
        -   *4*: `sixteenth <guitarpro.base.Duration.sixteenth>`_
        -   *5*: `eighth <guitarpro.base.Duration.eighth>`_
        -   *6*: `quarter <guitarpro.base.Duration.quarter>`_

        """
        if value == 1:
            return gp.Duration.sixtyFourth
        elif value == 2:
            return gp.Duration.sixtyFourth
        elif value == 3:
            return gp.Duration.thirtySecond
        elif value == 4:
            return gp.Duration.sixteenth
        elif value == 5:
            return gp.Duration.eighth
        elif value == 6:
            return gp.Duration.quarter
        else:
            return gp.Duration.sixtyFourth

    def readMixTableChange(self, measure):
        """Read mix table change.

        Mix table change is consists of 7 :ref:`SignedBytes <signed-byte>` and an :ref:`int`, which correspond to:

        -   instrument
        -   volume
        -   balance
        -   chorus
        -   reverb
        -   phaser
        -   tremolo
        -   tempo

        If signed byte is -1 then corresponding parameter hasn't changed.

        List of values is followed by the list of durations for parameters that have changed.

        """
        tableChange = gp.MixTableChange()
        self.readMixTableChangeValues(tableChange)
        self.readMixTableChangeDurations(tableChange, measure)
        return tableChange

    def readMixTableChangeValues(self, tableChange):
        instrument = self.readSignedByte()
        volume = self.readSignedByte()
        balance = self.readSignedByte()
        chorus = self.readSignedByte()
        reverb = self.readSignedByte()
        phaser = self.readSignedByte()
        tremolo = self.readSignedByte()
        tempo = self.readInt()
        if instrument >= 0:
            tableChange.instrument = gp.MixTableItem(instrument)
        if volume >= 0:
            tableChange.volume = gp.MixTableItem(volume)
        if balance >= 0:
            tableChange.balance = gp.MixTableItem(balance)
        if chorus >= 0:
            tableChange.chorus = gp.MixTableItem(chorus)
        if reverb >= 0:
            tableChange.reverb = gp.MixTableItem(reverb)
        if phaser >= 0:
            tableChange.phaser = gp.MixTableItem(phaser)
        if tremolo >= 0:
            tableChange.tremolo = gp.MixTableItem(tremolo)
        if tempo >= 0:
            tableChange.tempo = gp.MixTableItem(tempo)

    def readMixTableChangeDurations(self, tableChange, measure):
        if tableChange.volume is not None:
            tableChange.volume.duration = self.readSignedByte()
        if tableChange.balance is not None:
            tableChange.balance.duration = self.readSignedByte()
        if tableChange.chorus is not None:
            tableChange.chorus.duration = self.readSignedByte()
        if tableChange.reverb is not None:
            tableChange.reverb.duration = self.readSignedByte()
        if tableChange.phaser is not None:
            tableChange.phaser.duration = self.readSignedByte()
        if tableChange.tremolo is not None:
            tableChange.tremolo.duration = self.readSignedByte()
        if tableChange.tempo is not None:
            tableChange.tempo.duration = self.readSignedByte()
            measure.tempo.value = tableChange.tempo.value
            tableChange.hideTempo = False

    def readNotes(self, track, voice, duration, effect=None):
        """Read notes.

        First byte lists played strings:

        -   *0x01*: 7th string
        -   *0x02*: 6th string
        -   *0x04*: 5th string
        -   *0x08*: 4th string
        -   *0x10*: 3th string
        -   *0x20*: 2th string
        -   *0x40*: 1th string
        -   *0x80*: blank bit

        """
        stringFlags = self.readByte()
        for string in track.strings:
            if stringFlags & 1 << (7 - string.number):
                note = gp.Note()
                voice.addNote(note)
                if effect is None:
                    effect = gp.NoteEffect()
                self.readNote(note, string, track, effect)
            voice.duration = duration

    def readNote(self, note, guitarString, track, effect):
        """Read note.

        The first byte is note flags:

        -   *0x01*: time-independent duration
        -   *0x02*: heavy accentuated note
        -   *0x04*: ghost note
        -   *0x08*: presence of note effects
        -   *0x10*: dynamics
        -   *0x20*: fret
        -   *0x40*: accentuated note
        -   *0x80*: right hand or left hand fingering

        Flags are followed by:

        -   Note type: :ref:`byte`.
            Note is normal if values is 1, tied if value is 2, dead if value is 3.

        -   Time-independent duration: 2 :ref:`SignedBytes <signed-byte>`.
            Correspond to duration and tuplet.
            See :meth:`readDuration` for reference.

        -   Note dynamics: :ref:`signed-byte`.
            See :meth:`unpackVelocity`.

        -   Fret number: :ref:`signed-byte`.
            If flag at *0x20* is set then read fret number.

        -   Fingering: 2 :ref:`SignedBytes <signed-byte>`.
            See :class:`guitarpro.base.Fingering`.

        -   Note effects: :class:`guitarpro.base.NoteEffect`.
            See :meth:`readNoteEffects`.

        """
        flags = self.readByte()
        note.string = guitarString.number
        note.effect = effect
        note.effect.heavyAccentuatedNote = bool(flags & 0x02)
        note.effect.ghostNote = bool(flags & 0x04)
        note.effect.accentuatedNote = bool(flags & 0x40)
        if flags & 0x20:
            note.type = gp.NoteType(self.readByte())
            note.effect.deadNote = note.type == gp.NoteType.dead
        if flags & 0x01:
            note.duration = self.readSignedByte()
            note.tuplet = self.readSignedByte()
        if flags & 0x10:
            dyn = self.readSignedByte()
            note.velocity = self.unpackVelocity(dyn)
        if flags & 0x20:
            fret = self.readSignedByte()
            if note.type == gp.NoteType.tie:
                value = self.getTiedNoteValue(guitarString.number, track)
            else:
                value = fret
            note.value = max(0, min(99, value))
        if flags & 0x80:
            note.effect.leftHandFinger = gp.Fingering(self.readSignedByte())
            note.effect.rightHandFinger = gp.Fingering(self.readSignedByte())
        if flags & 0x08:
            self.readNoteEffects(note)
            if note.effect.isHarmonic and isinstance(note.effect.harmonic, gp.TappedHarmonic):
                note.effect.harmonic.fret = note.value + 12
        return note

    def unpackVelocity(self, dyn):
        """Convert Guitar Pro dynamic value to raw MIDI velocity."""
        return (gp.Velocities.minVelocity +
                gp.Velocities.velocityIncrement * dyn -
                gp.Velocities.velocityIncrement)

    def getTiedNoteValue(self, stringIndex, track):
        """Get note value of tied note."""
        for measure in reversed(track.measures):
            for beat in reversed(measure.beats):
                for voice in beat.voices:
                    if not voice.isEmpty:
                        for note in voice.notes:
                            if note.string == stringIndex:
                                return note.value
        return -1

    def readNoteEffects(self, note):
        """Read note effects.

        First byte is note effects flags:

        -   *0x01*: bend presence
        -   *0x02*: hammer-on/pull-off
        -   *0x04*: slide
        -   *0x08*: let-ring
        -   *0x10*: grace note presence

        Flags are followed by:

        -   Bend: :class:`guitarpro.base.BendEffect`.
            See :meth:`readBend`.

        -   Grace note: :class:`guitarpro.base.GraceEffect`.
            See :meth:`readGrace`.

        """
        noteEffect = note.effect
        flags1 = self.readByte()
        noteEffect.hammer = bool(flags1 & 0x02)
        noteEffect.slides = [gp.SlideType.legatoSlideTo] if flags1 & 0x04 else []
        noteEffect.letRing = bool(flags1 & 0x08)
        if flags1 & 0x01:
            self.readBend(noteEffect)
        if flags1 & 0x10:
            self.readGrace(noteEffect)

    def readBend(self, noteEffect):
        """Read bend.

        Encoded as:

        -   Bend type: :ref:`signed-byte`.
            See :class:`guitarpro.base.BendType`.

        -   Bend value: :ref:`int`.

        -   Number of bend points: :ref:`int`.

        -   List of points: :class:`guitarpro.base.BendPoint`.
            Each point consists of:

            *   Position: :ref:`int`.
                Shows where point is set along X axis.

            *   Value: :ref:`int`.
                Shows where point is set along Y axis.

            *   Vibrato: :ref:`bool`.

        """
        bendEffect = gp.BendEffect()
        bendEffect.type = gp.BendType(self.readSignedByte())
        bendEffect.value = self.readInt()
        pointCount = self.readInt()
        for i in range(pointCount):
            position = round(self.readInt() * gp.BendEffect.maxPosition /
                             gp.GPFileBase.bendPosition)
            value = round(self.readInt() * gp.BendEffect.semitoneLength /
                          gp.GPFileBase.bendSemitone)
            vibrato = self.readBool()
            bendEffect.points.append(gp.BendPoint(position, value, vibrato))
        if pointCount > 0:
            noteEffect.bend = bendEffect

    def readGrace(self, noteEffect):
        """Read grace note effect.

        -   Fret: :ref:`signed-byte`.
            Number of fret.

        -   Dynamic: :ref:`byte`.
            Dynamic of a grace note, as in :attr:`guitarpro.base.Note.velocity`.

        -   Transition: :ref:`byte`.
            See :class:`guitarpro.base.GraceEffectTransition`.

        -   Duration: :ref:`byte`.
            Values are:

            *   *1*: Thirty-second note.
            *   *2*: Twenty-fourth note.
            *   *3*: Sixteenth note.

        """
        fret = self.readSignedByte()
        dyn = self.readByte()
        transition = self.readSignedByte()
        duration = self.readByte()
        grace = gp.GraceEffect()

        grace.fret = fret
        grace.velocity = self.unpackVelocity(dyn)
        grace.duration = 1 << (7 - duration)
        grace.isDead = fret == -1
        grace.isOnBeat = False
        grace.transition = gp.GraceEffectTransition(transition)

        noteEffect.grace = grace

    # Writing
    # =======

    def writeSong(self, song):
        self.writeVersion(0)
        self.writeInfo(song)
        self._tripletFeel = song.tracks[0].measures[0].tripletFeel.value
        self.writeBool(self._tripletFeel)
        self.writeInt(song.tempo)
        self.writeInt(song.key.value[0])
        self.writeMidiChannels(song.tracks)
        measureCount = len(song.tracks[0].measures)
        trackCount = len(song.tracks)
        self.writeInt(measureCount)
        self.writeInt(trackCount)
        self.writeMeasureHeaders(song.tracks[0].measures)
        self.writeTracks(song.tracks)
        self.writeMeasures(song.tracks)
        self.writeInt(0)

    def writeInfo(self, song):
        self.writeIntByteSizeString(song.title)
        self.writeIntByteSizeString(song.subtitle)
        self.writeIntByteSizeString(song.artist)
        self.writeIntByteSizeString(song.album)
        self.writeIntByteSizeString(song.words)
        self.writeIntByteSizeString(song.copyright)
        self.writeIntByteSizeString(song.tab)
        self.writeIntByteSizeString(song.instructions)
        self.writeInt(len(song.notice))
        for line in song.notice:
            self.writeIntByteSizeString(line)

    def writeMidiChannels(self, tracks):
        def getTrackChannelByChannel(channel):
            for track in tracks:
                if channel in (track.channel.channel, track.channel.effectChannel):
                    return track.channel
            default = gp.MidiChannel()
            default.channel = channel
            default.effectChannel = channel
            if default.isPercussionChannel:
                default.instrument = 0
            return default
        for channel in map(getTrackChannelByChannel, range(64)):
            if channel.isPercussionChannel and channel.instrument == 0:
                self.writeInt(-1)
            else:
                self.writeInt(channel.instrument)
            self.writeSignedByte(self.fromChannelShort(channel.volume))
            self.writeSignedByte(self.fromChannelShort(channel.balance))
            self.writeSignedByte(self.fromChannelShort(channel.chorus))
            self.writeSignedByte(self.fromChannelShort(channel.reverb))
            self.writeSignedByte(self.fromChannelShort(channel.phaser))
            self.writeSignedByte(self.fromChannelShort(channel.tremolo))
            # Backward compatibility with version 3.0
            self.placeholder(2)

    def fromChannelShort(self, data):
        value = max(-128, min(127, (data >> 3) - 1))
        return value + 1

    def writeMeasureHeaders(self, measures):
        previous = None
        for measure in measures:
            self.writeMeasureHeader(measure.header, previous)
            previous = measure.header

    def writeMeasureHeader(self, header, previous=None):
        flags = 0x00
        if previous is not None:
            if header.timeSignature.numerator != previous.timeSignature.numerator:
                flags |= 0x01
            if header.timeSignature.denominator.value != previous.timeSignature.denominator.value:
                flags |= 0x02
        else:
            flags |= 0x01
            flags |= 0x02
        if header.isRepeatOpen:
            flags |= 0x04
        if header.repeatClose > -1:
            flags |= 0x08
        if header.repeatAlternative:
            flags |= 0x10
        if header.marker is not None:
            flags |= 0x20
        if previous is not None:
            if header.keySignature != previous.keySignature:
                flags |= 0x40
        elif header.keySignaturePresence:
            flags |= 0x40
        if header.hasDoubleBar:
            flags |= 0x80
        self.writeByte(flags)
        if flags & 0x01:
            self.writeSignedByte(header.timeSignature.numerator)
        if flags & 0x02:
            self.writeSignedByte(header.timeSignature.denominator.value)
        if flags & 0x08:
            self.writeSignedByte(header.repeatClose)
        if flags & 0x10:
            self.writeRepeatAlternative(header.repeatAlternative)
        if flags & 0x20:
            self.writeMarker(header.marker)
        if flags & 0x40:
            self.writeSignedByte(header.keySignature.value[0])
            self.writeSignedByte(header.keySignature.value[1])

    def writeRepeatAlternative(self, value):
        first_one = False
        for i in range(value.bit_length() + 1):
            if value & 1 << i:
                first_one = True
            elif first_one:
                break
        self.writeByte(i)

    def writeMarker(self, marker):
        self.writeIntByteSizeString(marker.title)
        self.writeColor(marker.color)

    def writeColor(self, color):
        self.writeByte(color.r)
        self.writeByte(color.g)
        self.writeByte(color.b)
        self.placeholder(1)

    def writeTracks(self, tracks):
        for track in tracks:
            self.writeTrack(track)

    def writeTrack(self, track):
        flags = 0x00
        if track.isPercussionTrack:
            flags |= 0x01
        if track.is12StringedGuitarTrack:
            flags |= 0x02
        if track.isBanjoTrack:
            flags |= 0x04
        self.writeByte(flags)
        self.writeByteSizeString(track.name, 40)
        self.writeInt(len(track.strings))
        for i in range(7):
            if i < len(track.strings):
                tuning = track.strings[i].value
            else:
                tuning = 0
            self.writeInt(tuning)
        self.writeInt(track.port)
        self.writeChannel(track)
        self.writeInt(track.fretCount)
        self.writeInt(track.offset)
        self.writeColor(track.color)

    def writeChannel(self, track):
        self.writeInt(track.channel.channel + 1)
        self.writeInt(track.channel.effectChannel + 1)

    def writeMeasures(self, tracks):
        partwiseMeasures = [track.measures for track in tracks]
        for timewiseMeasures in zip(*partwiseMeasures):
            for measure in timewiseMeasures:
                self.writeMeasure(measure)

    def writeMeasure(self, measure):
        beats = measure.voice(0)
        self.writeInt(len(beats))
        for beat in beats:
            self.writeBeat(beat)

    def writeBeat(self, beat, voiceIndex=0):
        voice = beat.voices[voiceIndex]
        flags = 0x00
        if voice.duration.isDotted:
            flags |= 0x01
        if beat.effect.isChord:
            flags |= 0x02
        if beat.text is not None:
            flags |= 0x04
        if (not beat.effect.isDefault or voice.hasVibrato or
                voice.hasHarmonic):
            flags |= 0x08
        if beat.effect.mixTableChange is not None:
            flags |= 0x10
        if voice.duration.tuplet != gp.Tuplet():
            flags |= 0x20
        if voice.isEmpty or voice.isRestVoice:
            flags |= 0x40
        self.writeByte(flags)
        if flags & 0x40:
            beatType = 0x00 if voice.isEmpty else 0x02
            self.writeByte(beatType)
        self.writeDuration(voice.duration, flags)
        if flags & 0x02:
            self.writeChord(beat.effect.chord)
        if flags & 0x04:
            self.writeText(beat.text)
        if flags & 0x08:
            self.writeBeatEffects(beat.effect, voice)
        if flags & 0x10:
            self.writeMixTableChange(beat.effect.mixTableChange)
        self.writeNotes(voice)

    def writeDuration(self, duration, flags):
        value = round(math.log(duration.value, 2) - 2)
        self.writeSignedByte(value)
        if flags & 0x20:
            if (duration.tuplet.enters, duration.tuplet.times) == (3, 2):
                iTuplet = 3
            elif (duration.tuplet.enters, duration.tuplet.times) == (5, 4):
                iTuplet = 5
            elif (duration.tuplet.enters, duration.tuplet.times) == (6, 4):
                iTuplet = 6
            elif (duration.tuplet.enters, duration.tuplet.times) == (7, 4):
                iTuplet = 7
            elif (duration.tuplet.enters, duration.tuplet.times) == (9, 8):
                iTuplet = 9
            elif (duration.tuplet.enters, duration.tuplet.times) == (10, 8):
                iTuplet = 10
            elif (duration.tuplet.enters, duration.tuplet.times) == (11, 8):
                iTuplet = 11
            elif (duration.tuplet.enters, duration.tuplet.times) == (12, 8):
                iTuplet = 12
            self.writeInt(iTuplet)

    def writeChord(self, chord):
        self.writeSignedByte(1)  # signify GP4 chord format
        self.writeBool(chord.sharp)
        self.placeholder(3)
        self.writeInt(chord.root.value if chord.root else 0)
        self.writeInt(chord.type.value if chord.type else 0)
        self.writeInt(chord.extension.value if chord.extension else 0)
        self.writeInt(chord.bass.value if chord.bass else 0)
        self.writeInt(chord.tonality.value if chord.tonality else 0)
        self.writeBool(chord.add)
        self.writeByteSizeString(chord.name, 22)
        self.writeInt(chord.fifth.value if chord.fifth else 0)
        self.writeInt(chord.ninth.value if chord.ninth else 0)
        self.writeInt(chord.eleventh.value if chord.eleventh else 0)
        self.writeInt(chord.firstFret)
        for fret in clamp(chord.strings, 6, fillvalue=-1):
            self.writeInt(fret)
        barres = chord.barres[:2]
        self.writeInt(len(barres))
        if barres:
            barreFrets, barreStarts, barreEnds = zip(*barres)
        else:
            barreFrets, barreStarts, barreEnds = [], [], []
        for fret in clamp(barreFrets, 2, fillvalue=0):
            self.writeInt(fret)
        for start in clamp(barreStarts, 2, fillvalue=0):
            self.writeInt(start)
        for end in clamp(barreEnds, 2, fillvalue=0):
            self.writeInt(end)
        for omission in clamp(chord.omissions, 7, fillvalue=True):
            self.writeBool(omission)
        self.placeholder(1)

    def writeText(self, text):
        self.writeIntByteSizeString(text.value)

    def writeBeatEffects(self, beatEffect, voice):
        flags1 = 0x00
        if voice.hasVibrato:
            flags1 |= 0x01
        if beatEffect.vibrato:
            flags1 |= 0x02
        if isinstance(voice.hasHarmonic, gp.NaturalHarmonic):
            flags1 |= 0x04
        if isinstance(voice.hasHarmonic, gp.ArtificialHarmonic):
            flags1 |= 0x08
        if beatEffect.fadeIn:
            flags1 |= 0x10
        if beatEffect.isTremoloBar or beatEffect.isSlapEffect:
            flags1 |= 0x20
        if beatEffect.stroke != gp.BeatStroke():
            flags1 |= 0x40
        self.writeByte(flags1)
        if flags1 & 0x20:
            self.writeByte(beatEffect.slapEffect.value)
            self.writeTremoloBar(beatEffect.tremoloBar)
        if flags1 & 0x40:
            self.writeBeatStroke(beatEffect.stroke)

    def writeTremoloBar(self, tremoloBar):
        if tremoloBar is not None:
            self.writeInt(tremoloBar.value)
        else:
            self.writeInt(0)

    def writeBeatStroke(self, stroke):
        if stroke.direction == gp.BeatStrokeDirection.up:
            strokeUp = self.fromStrokeValue(stroke.value)
            strokeDown = 0
        elif stroke.direction == gp.BeatStrokeDirection.down:
            strokeUp = 0
            strokeDown = self.fromStrokeValue(stroke.value)
        self.writeSignedByte(strokeUp)
        self.writeSignedByte(strokeDown)

    def fromStrokeValue(self, value):
        if value == gp.Duration.sixtyFourth:
            return 1
        elif value == gp.Duration.sixtyFourth:
            return 2
        elif value == gp.Duration.thirtySecond:
            return 3
        elif value == gp.Duration.sixteenth:
            return 4
        elif value == gp.Duration.eighth:
            return 5
        elif value == gp.Duration.quarter:
            return 6
        else:
            return 1

    def writeMixTableChange(self, tableChange):
        self.writeMixTableChangeValues(tableChange)
        self.writeMixTableChangeDurations(tableChange)

    def writeMixTableChangeValues(self, tableChange):
        self.writeSignedByte(tableChange.instrument.value
                             if tableChange.instrument is not None else -1)
        self.writeSignedByte(tableChange.volume.value
                             if tableChange.volume is not None else -1)
        self.writeSignedByte(tableChange.balance.value
                             if tableChange.balance is not None else -1)
        self.writeSignedByte(tableChange.chorus.value
                             if tableChange.chorus is not None else -1)
        self.writeSignedByte(tableChange.reverb.value
                             if tableChange.reverb is not None else -1)
        self.writeSignedByte(tableChange.phaser.value
                             if tableChange.phaser is not None else -1)
        self.writeSignedByte(tableChange.tremolo.value
                             if tableChange.tremolo is not None else -1)
        self.writeInt(tableChange.tempo.value
                      if tableChange.tempo is not None else -1)

    def writeMixTableChangeDurations(self, tableChange):
        if tableChange.volume is not None:
            self.writeSignedByte(tableChange.volume.duration)
        if tableChange.balance is not None:
            self.writeSignedByte(tableChange.balance.duration)
        if tableChange.chorus is not None:
            self.writeSignedByte(tableChange.chorus.duration)
        if tableChange.reverb is not None:
            self.writeSignedByte(tableChange.reverb.duration)
        if tableChange.phaser is not None:
            self.writeSignedByte(tableChange.phaser.duration)
        if tableChange.tremolo is not None:
            self.writeSignedByte(tableChange.tremolo.duration)
        if tableChange.tempo is not None:
            self.writeSignedByte(tableChange.tempo.duration)

    def writeNotes(self, voice):
        stringFlags = 0x00
        for note in voice.notes:
            stringFlags |= 1 << (7 - note.string)
        self.writeByte(stringFlags)
        for note in voice.notes:
            self.writeNote(note)

    def writeNote(self, note):
        noteEffect = note.effect
        flags = 0x00
        try:
            if note.duration is not None and note.tuplet is not None:
                flags |= 0x01
        except AttributeError:
            pass
        if note.effect.heavyAccentuatedNote:
            flags |= 0x02
        if note.effect.ghostNote:
            flags |= 0x04
        if not noteEffect.isDefault:
            flags |= 0x08
        if note.velocity != gp.Velocities.default:
            flags |= 0x10
        flags |= 0x20
        if note.effect.accentuatedNote:
            flags |= 0x40
        if note.effect.isFingering:
            flags |= 0x80
        self.writeByte(flags)
        if flags & 0x20:
            self.writeByte(note.type.value)
        if flags & 0x01:
            self.writeSignedByte(note.duration)
            self.writeSignedByte(note.tuplet)
        if flags & 0x10:
            value = self.packVelocity(note.velocity)
            self.writeSignedByte(value)
        if flags & 0x20:
            fret = note.value if note.type != gp.NoteType.tie else 0
            self.writeSignedByte(fret)
        if flags & 0x80:
            self.writeSignedByte(note.effect.leftHandFinger.value)
            self.writeSignedByte(note.effect.rightHandFinger.value)
        if flags & 0x08:
            self.writeNoteEffects(note)

    def writeNoteEffects(self, note):
        noteEffect = note.effect
        flags1 = 0x00
        if noteEffect.isBend:
            flags1 |= 0x01
        if noteEffect.hammer:
            flags1 |= 0x02
        if (gp.SlideType.shiftSlideTo in noteEffect.slides or
                gp.SlideType.legatoSlideTo in noteEffect.slides):
            flags1 |= 0x04
        if noteEffect.letRing:
            flags1 |= 0x08
        if noteEffect.isGrace:
            flags1 |= 0x10
        self.writeByte(flags1)
        if flags1 & 0x01:
            self.writeBend(noteEffect.bend)
        if flags1 & 0x10:
            self.writeGrace(noteEffect.grace)

    def writeBend(self, bend):
        self.writeSignedByte(bend.type.value)
        self.writeInt(bend.value)
        self.writeInt(len(bend.points))
        for point in bend.points:
            self.writeInt(round(point.position * self.bendPosition /
                                gp.BendEffect.maxPosition))
            self.writeInt(round(point.value * self.bendSemitone /
                                gp.BendEffect.semitoneLength))
            self.writeBool(point.vibrato)

    def writeGrace(self, grace):
        self.writeByte(grace.fret)
        self.writeByte(self.packVelocity(grace.velocity))
        self.writeSignedByte(grace.transition.value)
        self.writeByte(8 - grace.duration.bit_length())

    def packVelocity(self, velocity):
        return ((velocity + gp.Velocities.velocityIncrement -
                 gp.Velocities.minVelocity) / gp.Velocities.velocityIncrement)
