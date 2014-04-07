#!/usr/bin/env python
#
# Copyright (C) 2011, 2012  Google Inc.
#
# This file is part of YouCompleteMe.
#
# YouCompleteMe is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# YouCompleteMe is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with YouCompleteMe.  If not, see <http://www.gnu.org/licenses/>.

from collections import defaultdict
import ycm_core
from ycm.server import responses
from ycm import extra_conf_store
from ycm.utils import ToUtf8IfNeeded
from ycm.completers.completer import Completer
from ycm.completers.cpp.flags import Flags, PrepareFlagsForClang
import linecache
import yacbi

CLANG_FILETYPES = set( [ 'c', 'cpp', 'objc', 'objcpp' ] )
MIN_LINES_IN_FILE_TO_PARSE = 5
PARSING_FILE_MESSAGE = 'Still parsing file, no completions yet.'
NO_COMPILE_FLAGS_MESSAGE = 'Still no compile flags, no completions yet.'
INVALID_FILE_MESSAGE = 'File is invalid.'
NO_COMPLETIONS_MESSAGE = 'No completions found; errors in the file?'
FILE_TOO_SHORT_MESSAGE = (
  'File is less than {0} lines long; not compiling.'.format(
    MIN_LINES_IN_FILE_TO_PARSE ) )
NO_DIAGNOSTIC_MESSAGE = 'No diagnostic for current line!'
PRAGMA_DIAG_TEXT_TO_IGNORE = '#pragma once in main file'
TOO_MANY_ERRORS_DIAG_TEXT_TO_IGNORE = 'too many errors emitted, stopping now'


class ClangCompleter( Completer ):
  def __init__( self, user_options ):
    super( ClangCompleter, self ).__init__( user_options )
    self._max_diagnostics_to_display = user_options[
      'max_diagnostics_to_display' ]
    self._completer = ycm_core.ClangCompleter()
    self._flags = Flags()
    self._diagnostic_store = None


  def SupportedFiletypes( self ):
    return CLANG_FILETYPES


  def GetUnsavedFilesVector( self, request_data ):
    files = ycm_core.UnsavedFileVec()
    for filename, file_data in request_data[ 'file_data' ].iteritems():
      if not ClangAvailableForFiletypes( file_data[ 'filetypes' ] ):
        continue
      contents = file_data[ 'contents' ]
      if not contents or not filename:
        continue

      unsaved_file = ycm_core.UnsavedFile()
      utf8_contents = ToUtf8IfNeeded( contents )
      unsaved_file.contents_ = utf8_contents
      unsaved_file.length_ = len( utf8_contents )
      unsaved_file.filename_ = ToUtf8IfNeeded( filename )

      files.append( unsaved_file )
    return files


  def ComputeCandidatesInner( self, request_data ):
    filename = request_data[ 'filepath' ]
    if not filename:
      return

    if self._completer.UpdatingTranslationUnit( ToUtf8IfNeeded( filename ) ):
      raise RuntimeError( PARSING_FILE_MESSAGE )

    flags = self._FlagsForRequest( request_data )
    if not flags:
      raise RuntimeError( NO_COMPILE_FLAGS_MESSAGE )

    files = self.GetUnsavedFilesVector( request_data )
    line = request_data[ 'line_num' ] + 1
    column = request_data[ 'start_column' ] + 1
    results = self._completer.CandidatesForLocationInFile(
        ToUtf8IfNeeded( filename ),
        line,
        column,
        files,
        flags )

    if not results:
      raise RuntimeError( NO_COMPLETIONS_MESSAGE )

    return [ ConvertCompletionData( x ) for x in results ]


  def DefinedSubcommands( self ):
    return [ 'GoToDefinition',
             'GoToDeclaration',
             'GoTo',
             'GoToImprecise',
             'GoToIncludedFile',
             'GoToIncludedFileImprecise',
             'QueryReferences',
             'QueryReferencesImprecise',
             'QueryIncludingFiles',
             'QuerySubtypes',
             'QuerySubtypesImprecise',
             'ClearCompilationFlagCache']


  def OnUserCommand( self, arguments, request_data ):
    if not arguments:
      raise ValueError( self.UserCommandsHelpMessage() )

    command = arguments[ 0 ]
    if command == 'GoToDefinition':
      return self._GoToDefinition( request_data )
    elif command == 'GoToDeclaration':
      return self._GoToDeclaration( request_data )
    elif command == 'GoTo':
      return self._GoTo( request_data, True )
    elif command == 'GoToImprecise':
      return self._GoTo( request_data, False )
    elif command == 'GoToIncludedFile':
      return self._GoToIncludedFile( request_data, True )
    elif command == 'GoToIncludedFileImprecise':
      return self._GoToIncludedFile( request_data, False )
    elif command == 'QueryReferences':
      return self._QueryReferences( request_data, True )
    elif command == 'QueryReferencesImprecise':
      return self._QueryReferences( request_data, False )
    elif command == 'QueryIncludingFiles':
      return self._QueryIncludingFiles( request_data )
    elif command == 'QuerySubtypes':
      return self._QuerySubtypes( request_data, True )
    elif command == 'QuerySubtypesImprecise':
      return self._QuerySubtypes( request_data, False )
    elif command == 'ClearCompilationFlagCache':
      return self._ClearCompilationFlagCache()
    raise ValueError( self.UserCommandsHelpMessage() )


  def _LocationForGoTo( self, goto_function, request_data, reparse = True ):
    filename = request_data[ 'filepath' ]
    if not filename:
      raise ValueError( INVALID_FILE_MESSAGE )

    flags = self._FlagsForRequest( request_data )
    if not flags:
      raise ValueError( NO_COMPILE_FLAGS_MESSAGE )

    files = self.GetUnsavedFilesVector( request_data )
    line = request_data[ 'line_num' ] + 1
    column = request_data[ 'column_num' ] + 1
    return getattr( self._completer, goto_function )(
        ToUtf8IfNeeded( filename ),
        line,
        column,
        files,
        flags,
        reparse )


  def _GoToDefinition( self, request_data ):
    location = self._LocationForGoTo( 'GetDefinitionLocation', request_data )
    if location and location.IsValid():
      return _ResponseForLocation( location )
    filename = request_data[ 'filepath' ]
    if not filename:
      raise ValueError( INVALID_FILE_MESSAGE )
    usr = self._GetUsr( request_data, True )
    if usr:
      root_dir = yacbi.get_root_for_path( filename )
      if root_dir:
        defs = yacbi.query_definitions( root_dir, usr )
        if defs:
          locations = [{ 'filepath': d.location.filename,
                         'line_num': d.location.line - 1,
                         'column_num': d.location.column - 1 } for d in defs]
          if len( locations ) == 1:
            return locations[ 0 ]
          else:
            return locations;
    raise RuntimeError( 'Can\'t jump to definition.' )


  def _GoToDeclaration( self, request_data ):
    location = self._LocationForGoTo( 'GetDeclarationLocation', request_data )
    if not location or not location.IsValid():
      raise RuntimeError( 'Can\'t jump to declaration.' )
    return _ResponseForLocation( location )


  def _GoToIncludedFile( self, request_data, reparse ):
    location = self._LocationForGoTo( 'GetIncludedFileLocation',
                                      request_data,
                                      reparse )
    if not location or not location.IsValid():
      raise RuntimeError( 'Can\'t jump to included file.' )
    return _ResponseForLocation( location )


  def _GoTo( self, request_data, reparse ):
    location = self._LocationForGoTo( 'GetDefinitionLocation',
                                      request_data,
                                      reparse )
    if location and location.IsValid():
      return _ResponseForLocation( location )
    location = self._LocationForGoTo( 'GetIncludedFileLocation',
                                      request_data,
                                      reparse )
    if location and location.IsValid():
      return _ResponseForLocation( location )
    location = None
    filename = request_data[ 'filepath' ]
    if not filename:
      raise ValueError( INVALID_FILE_MESSAGE )
    usr = self._GetUsr( request_data, reparse )
    if usr:
      root_dir = yacbi.get_root_for_path( filename )
      if root_dir:
        defs = yacbi.query_definitions( root_dir, usr )
        if defs:
          locations = [{ 'filepath': d.location.filename,
                         'line_num': d.location.line - 1,
                         'column_num': d.location.column - 1 } for d in defs]
          if len( locations ) == 1:
            return locations[ 0 ]
          else:
            return locations;
    if not location:
      location = self._LocationForGoTo( 'GetDeclarationLocation',
                                         request_data,
                                         reparse )
    if not location or not location.IsValid():
      raise RuntimeError( 'Can\'t jump to definition or declaration.' )
    return _ResponseForLocation( location )


  def _GetUsr( self, request_data, reparse ):
    filename = request_data[ 'filepath' ]
    if not filename:
      raise ValueError( INVALID_FILE_MESSAGE )

    flags = self._FlagsForRequest( request_data )
    if not flags:
      raise ValueError( NO_COMPILE_FLAGS_MESSAGE )

    files = self.GetUnsavedFilesVector( request_data )
    line = request_data[ 'line_num' ] + 1
    column = request_data[ 'column_num' ] + 1
    usr = getattr( self._completer, "GetUsrForLocation" )(
      ToUtf8IfNeeded( filename ),
      line,
      column,
      files,
      flags,
      reparse )
    return usr


  def _QueryReferences( self, request_data, reparse ):
    filename = request_data[ 'filepath' ]
    if not filename:
      raise ValueError( INVALID_FILE_MESSAGE )
    usr = self._GetUsr( request_data, reparse )
    root_dir = yacbi.get_root_for_path( filename )
    if not root_dir:
      raise RuntimeError( 'Could not find yacbi database file.' )
    refs = yacbi.query_references( root_dir, usr )
    result = []
    linecache.checkcache()
    for r in refs:
      loc = r.location
      txt = linecache.getline( loc.filename, loc.line ).strip()
      if txt:
        desc = r.description + ': ' + txt
      else:
        desc = r.description
      result.append( { 'filepath': loc.filename,
                       'description': desc,
                       'line_num': loc.line - 1,
                       'column_num': loc.column } )
    return result


  def _QueryIncludingFiles( self, request_data ):
    filename = request_data[ 'filepath' ]
    if not filename:
      raise ValueError( INVALID_FILE_MESSAGE )
    root_dir = yacbi.get_root_for_path( filename )
    if not root_dir:
      raise RuntimeError( 'Could not find yacbi database file.' )
    locations = yacbi.query_including_files( root_dir, filename )
    result = []
    linecache.checkcache()
    for loc in locations:
      desc = linecache.getline( loc.filename, loc.line ).strip()
      result.append( { 'filepath': loc.filename,
                       'description': desc,
                       'line_num': loc.line - 1,
                       'column_num': loc.column } )
    return result


  def _QuerySubtypes( self, request_data, reparse ):
    # TODO refactor to avoid duplication
    filename = request_data[ 'filepath' ]
    if not filename:
      raise ValueError( INVALID_FILE_MESSAGE )
    usr = self._GetUsr( request_data, reparse )
    root_dir = yacbi.get_root_for_path( filename )
    if not root_dir:
      raise RuntimeError( 'Could not find yacbi database file.' )
    refs = yacbi.query_subtypes( root_dir, usr )
    result = []
    linecache.checkcache()
    for r in refs:
      loc = r.location
      txt = linecache.getline( loc.filename, loc.line ).strip()
      if txt:
        desc = r.description + ': ' + txt
      else:
        desc = r.description
      result.append( { 'filepath': loc.filename,
                       'description': desc,
                       'line_num': loc.line - 1,
                       'column_num': loc.column } )
    return result


  def _ClearCompilationFlagCache( self ):
    self._flags.Clear()


  def OnFileReadyToParse( self, request_data ):
    filename = request_data[ 'filepath' ]
    contents = request_data[ 'file_data' ][ filename ][ 'contents' ]
    if contents.count( '\n' ) < MIN_LINES_IN_FILE_TO_PARSE:
      raise ValueError( FILE_TOO_SHORT_MESSAGE )

    if not filename:
      raise ValueError( INVALID_FILE_MESSAGE )

    flags = self._FlagsForRequest( request_data )
    if not flags:
      raise ValueError( NO_COMPILE_FLAGS_MESSAGE )

    diagnostics = self._completer.UpdateTranslationUnit(
      ToUtf8IfNeeded( filename ),
      self.GetUnsavedFilesVector( request_data ),
      flags )

    diagnostics = _FilterDiagnostics( diagnostics )
    self._diagnostic_store = DiagnosticsToDiagStructure( diagnostics )
    return [ responses.BuildDiagnosticData( x ) for x in
             diagnostics[ : self._max_diagnostics_to_display ] ]


  def OnBufferUnload( self, request_data ):
    self._completer.DeleteCachesForFile(
        ToUtf8IfNeeded( request_data[ 'unloaded_buffer' ] ) )


  def GetDetailedDiagnostic( self, request_data ):
    current_line = request_data[ 'line_num' ] + 1
    current_column = request_data[ 'column_num' ] + 1
    current_file = request_data[ 'filepath' ]

    if not self._diagnostic_store:
      raise ValueError( NO_DIAGNOSTIC_MESSAGE )

    diagnostics = self._diagnostic_store[ current_file ][ current_line ]
    if not diagnostics:
      raise ValueError( NO_DIAGNOSTIC_MESSAGE )

    closest_diagnostic = None
    distance_to_closest_diagnostic = 999

    for diagnostic in diagnostics:
      distance = abs( current_column - diagnostic.location_.column_number_ )
      if distance < distance_to_closest_diagnostic:
        distance_to_closest_diagnostic = distance
        closest_diagnostic = diagnostic

    return responses.BuildDisplayMessageResponse(
      closest_diagnostic.long_formatted_text_ )


  def DebugInfo( self, request_data ):
    filename = request_data[ 'filepath' ]
    if not filename:
      return ''
    flags = self._FlagsForRequest( request_data ) or []
    source = extra_conf_store.ModuleFileForSourceFile( filename )
    return 'Flags for {0} loaded from {1}:\n{2}'.format( filename,
                                                         source,
                                                         list( flags ) )


  def _FlagsForRequest( self, request_data ):
    filename = ToUtf8IfNeeded( request_data[ 'filepath' ] )
    if 'compilation_flags' in request_data:
      return PrepareFlagsForClang( request_data[ 'compilation_flags' ],
                                   filename )
    client_data = request_data.get( 'extra_conf_data', None )
    return self._flags.FlagsForFile( filename, client_data = client_data )


def ConvertCompletionData( completion_data ):
  return responses.BuildCompletionData(
    insertion_text = completion_data.TextToInsertInBuffer(),
    menu_text = completion_data.MainCompletionText(),
    extra_menu_info = completion_data.ExtraMenuInfo(),
    kind = completion_data.kind_,
    detailed_info = completion_data.DetailedInfoForPreviewWindow() )


def DiagnosticsToDiagStructure( diagnostics ):
  structure = defaultdict( lambda : defaultdict( list ) )
  for diagnostic in diagnostics:
    structure[ diagnostic.location_.filename_ ][
      diagnostic.location_.line_number_ ].append( diagnostic )
  return structure


def ClangAvailableForFiletypes( filetypes ):
  return any( [ filetype in CLANG_FILETYPES for filetype in filetypes ] )


def InCFamilyFile( filetypes ):
  return ClangAvailableForFiletypes( filetypes )


def _FilterDiagnostics( diagnostics ):
  # Clang has an annoying warning that shows up when we try to compile header
  # files if the header has "#pragma once" inside it. The error is not
  # legitimate because it shows up because libclang thinks we are compiling a
  # source file instead of a header file.
  #
  # See our issue #216 and upstream bug:
  #   http://llvm.org/bugs/show_bug.cgi?id=16686
  #
  # The second thing we want to filter out are those incredibly annoying "too
  # many errors emitted" diagnostics that are utterly useless.
  return [ x for x in diagnostics if
           x.text_ != PRAGMA_DIAG_TEXT_TO_IGNORE and
           x.text_ != TOO_MANY_ERRORS_DIAG_TEXT_TO_IGNORE ]


def _ResponseForLocation( location ):
  return responses.BuildGoToResponse( location.filename_,
                                      location.line_number_ - 1,
                                      location.column_number_ - 1)


