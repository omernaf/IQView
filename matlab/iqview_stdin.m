function iqview_stdin(data, fs, fc, type)
%IQVIEW_STDIN  Open IQView Spectrogram Viewer with data piped directly from
%              MATLAB's workspace — no intermediate file written to disk.
%
%   The function converts your complex IQ vector to interleaved float32
%   binary bytes and streams them into IQView via its stdin pipe.
%
%   Usage:
%       iqview_stdin(data, fs)
%       iqview_stdin(data, fs, fc)
%       iqview_stdin(data, fs, fc, 'complex64')
%
%   Parameters:
%       data  - Complex vector of IQ samples (any numeric type, will be
%               converted to single-precision complex internally).
%       fs    - Sample rate in Hz  (e.g. 2e6 for 2 MHz)
%       fc    - Center frequency in Hz (default: 0)
%       type  - IQ data type string passed to IQView (default: 'complex64')
%
%   Example:
%       fs   = 2e6;
% t = (0 : fs * 0.5 - 1)' / fs;
% data = 0.8 * exp(2j * pi * 250e3 * t) + ...
% CW at + 250 kHz % 0.4 * exp(2j * pi * -150e3 * t);
% CW at - 150 kHz % iqview_stdin(data, fs);
%
% Requirements:
% -Python 3.x with IQView installed(or run from the project root)
% -MATLAB R2009b + (uses Java ProcessBuilder, no toolbox required)
% -- -Defaults-- -
if nargin < 3 || isempty(fc)
    fc = 0;
end
if nargin < 4 || isempty(type) 
    type = 'complex64';
end

% -- -Paths(edit these to match your environment)-- -
python_exe = 'd:\Projects\IQView\.venv\Scripts\python.exe';
iqview_main = 'd:\Projects\IQView\iqview\main.py';

% -- -Convert data to interleaved float32 bytes-- - 
% Flatten to column vector, cast to single precision 
data_single = single(data( :));

% Interleave real and imaginary parts : [ r0, i0, r1, i1, ... ] 
interleaved = zeros(2 * numel(data_single), 1, 'single');
interleaved(1 : 2 : end) = real(data_single);
interleaved(2 : 2 : end) = imag(data_single);

% Reinterpret float32 memory as raw uint8 bytes 
byte_data = typecast(interleaved, 'uint8');

% -- -Build the command arguments list-- - 
cmd_args = {python_exe,iqview_main, '--stdin', '-r', num2str(fs, '%.6g'), '-c', num2str(fc, '%.6g'), '-t', type};

% -- -Launch IQView via Java ProcessBuilder-- -
% ProcessBuilder lets us write binary data to the child's stdin, 
%which MATLAB's system() cannot do. 
pb = java.lang.ProcessBuilder(cmd_args);

% Merge IQView 's stderr into its stdout so MATLAB' sconsole shows messages 
pb.redirectErrorStream(true);

fprintf('Launching IQView and streaming %d samples (%.2f MB)...\n', numel(data_single), numel(byte_data) / 1024 ^ 2);

proc = pb.start();

% -- -Stream bytes to stdin-- - 
stdin_stream = proc.getOutputStream();
% Java calls this "output" from our side 
stdin_stream.write(byte_data, 0,numel(byte_data));
stdin_stream.flush();
stdin_stream.close();
% EOF — tells Python's sys.stdin.buffer.read() to return

fprintf('Data sent. IQView is loading...\n');
% IQView runs independently; we do not wait for it to exit.
end
