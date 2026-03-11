function iqview_stdin(data, fs, fc, type)
%IQVIEW_STDIN  Open IQView Spectrogram Viewer with data piped directly from
%              MATLAB's workspace - no intermediate file written to disk.
%
%   Usage:
%       iqview_stdin(data, fs)
%       iqview_stdin(data, fs, fc)
%       iqview_stdin(data, fs, fc, 'complex64')
%
%   Parameters:
%       data  - Complex vector of IQ samples (converted to float32 internally)
%       fs    - Sample rate in Hz  (e.g. 2e6 for 2 MHz)
%       fc    - Center frequency in Hz (default: 0)
%       type  - IQ data type string passed to IQView (default: 'complex64')
%
%   Example:
%       fs   = 2e6;
% t = (0 : fs * 0.5 - 1)' / fs;
% data = 0.8 * exp(2j * pi * 250e3 * t) + 0.4 * exp(2j * pi * -150e3 * t);
% iqview_stdin(data, fs);
%
% Requirements:
% -Python 3.x with IQView installed(or run from the project root)
% -MATLAB R2009b + (uses Java ProcessBuilder, no toolbox required)

if nargin < 3 || isempty(fc)
    fc = 0;
end
if nargin < 4 || isempty(type)
    type = 'complex64';
end

% Convert data to interleaved float32 bytes: [ r0, i0, r1, i1, ... ]
data_single = single(data( :));
interleaved = zeros(2 * numel(data_single), 1, 'single');
interleaved(1 : 2 : end) = real(data_single);
interleaved(2 : 2 : end) = imag(data_single);
byte_data = typecast(interleaved, 'uint8');
total_bytes = numel(byte_data);
% Build argument list and launch IQView via Java ProcessBuilder
% (ProcessBuilder is used because MATLAB's system() can't write to a subprocess's stdin)
cmd_args = {'iqview', '--stdin', '-r', num2str(fs, '%.6g'), '-c', num2str(fc, '%.6g'), '-t', type};
pb = java.lang.ProcessBuilder(cmd_args);
pb.redirectErrorStream(true);

fprintf('Launching IQView and streaming %d samples (%.2f MB)...\n', numel(data_single), total_bytes / 1024^2);
proc = pb.start();
stdin_stream = proc.getOutputStream();

chunk_size = 64 * 1024 * 1024;
total_bytes = numel(byte_data);
for i = 1:chunk_size:total_bytes
    end_idx = min(i + chunk_size - 1, total_bytes);
    current_chunk = byte_data(i:end_idx);
    stdin_stream.write(current_chunk); 
end

stdin_stream.flush();
stdin_stream.close();
% EOF - signals Python's sys.stdin.buffer.read() to return

fprintf('Data sent (%.2f MB). IQView is loading...\n', total_bytes / 1024^2);
% IQView runs independently; we do not wait for it to exit.
end
